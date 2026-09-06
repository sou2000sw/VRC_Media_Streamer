// native/app_audio_capture/src/main.cpp
// App Audio Capture Auxiliary Executable (Phase P0)
// Uses Windows WASAPI Process Loopback API to capture audio from a specific PID.

#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <wrl/client.h>

#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <chrono>
#include <thread>
#include <io.h>
#include <fcntl.h>

using Microsoft::WRL::ComPtr;

// WAV Header struct for 16-bit PCM
#pragma pack(push, 1)
struct WavHeader {
    char riffTag[4] = {'R', 'I', 'F', 'F'};
    uint32_t riffSize = 0; // 36 + dataSize
    char waveTag[4] = {'W', 'A', 'V', 'E'};
    char fmtTag[4] = {'f', 'm', 't', ' '};
    uint32_t fmtSize = 16;
    uint16_t audioFormat = 1; // PCM
    uint16_t numChannels = 2;
    uint32_t sampleRate = 48000;
    uint32_t byteRate = 48000 * 2 * 2;
    uint16_t blockAlign = 4;
    uint16_t bitsPerSample = 16;
    char dataTag[4] = {'d', 'a', 't', 'a'};
    uint32_t dataSize = 0;
};
#pragma pack(pop)

// Convert 32-bit float to 16-bit PCM with clamping (-1.0f..1.0f -> -32768..32767)
static inline int16_t FloatToS16(float v) {
    if (v > 1.0f) v = 1.0f;
    if (v < -1.0f) v = -1.0f;
    return static_cast<int16_t>(v * 32767.0f);
}

// Check if target PID exists
static bool ProcessExists(DWORD pid) {
    if (pid == 0) return false;
    HANDLE hProcess = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (hProcess != NULL) {
        DWORD exitCode = 0;
        BOOL res = GetExitCodeProcess(hProcess, &exitCode);
        CloseHandle(hProcess);
        return (res && exitCode == STILL_ACTIVE);
    }
    DWORD err = GetLastError();
    if (err == ERROR_ACCESS_DENIED) {
        return true;
    }
    return false;
}

// Custom completion handler implementing IActivateAudioInterfaceCompletionHandler & IAgileObject
class ActivateCompletionHandler : public IActivateAudioInterfaceCompletionHandler, public IAgileObject {
private:
    LONG m_refCount;

public:
    HANDLE eventHandle;
    HRESULT completionHr;
    ComPtr<IUnknown> audioInterface;

    ActivateCompletionHandler() : m_refCount(1), completionHr(E_FAIL) {
        eventHandle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    }

    ~ActivateCompletionHandler() {
        if (eventHandle) {
            CloseHandle(eventHandle);
        }
    }

    // IUnknown implementation
    STDMETHODIMP QueryInterface(REFIID riid, void** ppvObject) override {
        if (!ppvObject) return E_POINTER;
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IActivateAudioInterfaceCompletionHandler)) {
            *ppvObject = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
            AddRef();
            return S_OK;
        }
        if (riid == __uuidof(IAgileObject)) {
            *ppvObject = static_cast<IAgileObject*>(this);
            AddRef();
            return S_OK;
        }
        *ppvObject = nullptr;
        return E_NOINTERFACE;
    }

    STDMETHODIMP_(ULONG) AddRef() override {
        return InterlockedIncrement(&m_refCount);
    }

    STDMETHODIMP_(ULONG) Release() override {
        ULONG count = InterlockedDecrement(&m_refCount);
        if (count == 0) {
            delete this;
        }
        return count;
    }

    // IActivateAudioInterfaceCompletionHandler implementation
    STDMETHODIMP ActivateCompleted(IActivateAudioInterfaceAsyncOperation* activateOperation) override {
        HRESULT hrActivate = E_FAIL;
        ComPtr<IUnknown> unk;
        HRESULT hr = activateOperation->GetActivateResult(&hrActivate, &unk);
        if (SUCCEEDED(hr) && SUCCEEDED(hrActivate)) {
            completionHr = S_OK;
            audioInterface = unk;
        } else {
            completionHr = SUCCEEDED(hr) ? hrActivate : hr;
        }
        SetEvent(eventHandle);
        return S_OK;
    }
};

// Helper function to activate WASAPI Process Loopback IAudioClient
static HRESULT ActivateProcessLoopbackClient(DWORD pid, bool includeTree, ComPtr<IAudioClient>& outAudioClient) {
    AUDIOCLIENT_ACTIVATION_PARAMS params = {};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = includeTree ?
        PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE :
        PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE;

    PROPVARIANT pv = {};
    pv.vt = VT_BLOB;
    pv.blob.cbSize = sizeof(params);
    pv.blob.pBlobData = reinterpret_cast<BYTE*>(&params);

    ActivateCompletionHandler* pHandlerRaw = new ActivateCompletionHandler();
    ComPtr<IActivateAudioInterfaceCompletionHandler> handler;
    handler.Attach(pHandlerRaw);

    ComPtr<IActivateAudioInterfaceAsyncOperation> asyncOp;
    HRESULT hr = ActivateAudioInterfaceAsync(
        VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        __uuidof(IAudioClient),
        &pv,
        handler.Get(),
        &asyncOp
    );

    if (FAILED(hr)) {
        return hr;
    }

    DWORD waitResult = WaitForSingleObject(pHandlerRaw->eventHandle, 5000);
    if (waitResult != WAIT_OBJECT_0) {
        return E_FAIL;
    }

    if (FAILED(pHandlerRaw->completionHr)) {
        return pHandlerRaw->completionHr;
    }

    return pHandlerRaw->audioInterface.As(&outAudioClient);
}

int main(int argc, char* argv[]) {
    DWORD pid = 0;
    bool includeTree = true;
    int rate = 48000;
    int channels = 2;
    std::string wavPath;
    int seconds = 10;
    bool probe = false;

    // Parse command line arguments
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--pid" && i + 1 < argc) {
            pid = static_cast<DWORD>(std::stoul(argv[++i]));
        } else if (arg == "--mode" && i + 1 < argc) {
            std::string modeStr = argv[++i];
            if (modeStr == "include") {
                includeTree = true;
            } else if (modeStr == "exclude") {
                includeTree = false;
            } else {
                fprintf(stderr, "[AppAudio] Invalid mode argument: %s\n", modeStr.c_str());
                return 1;
            }
        } else if (arg == "--rate" && i + 1 < argc) {
            rate = std::stoi(argv[++i]);
        } else if (arg == "--channels" && i + 1 < argc) {
            channels = std::stoi(argv[++i]);
        } else if (arg == "--wav" && i + 1 < argc) {
            wavPath = argv[++i];
        } else if (arg == "--seconds" && i + 1 < argc) {
            seconds = std::stoi(argv[++i]);
        } else if (arg == "--probe") {
            probe = true;
        } else {
            fprintf(stderr, "[AppAudio] Unknown or invalid argument: %s\n", arg.c_str());
            return 1;
        }
    }

    if (pid == 0) {
        fprintf(stderr, "[AppAudio] Missing required argument: --pid <PID>\n");
        return 1;
    }

    // Exit code 3 if target process does not exist
    if (!ProcessExists(pid)) {
        fprintf(stderr, "[AppAudio] Target process %lu does not exist\n", pid);
        return 3;
    }

    // Initialize COM (MTA required)
    HRESULT hrCo = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hrCo)) {
        fprintf(stderr, "[AppAudio] CoInitializeEx failed: 0x%08X\n", hrCo);
        return 2;
    }

    ComPtr<IAudioClient> audioClient;
    HRESULT hrAct = ActivateProcessLoopbackClient(pid, includeTree, audioClient);
    if (FAILED(hrAct)) {
        fprintf(stderr, "[AppAudio] ActivateProcessLoopbackClient failed: 0x%08X\n", hrAct);
        if (hrAct == E_NOTIMPL || hrAct == E_NOINTERFACE || hrAct == HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED)) {
            CoUninitialize();
            return 4; // OS not supported
        }
        CoUninitialize();
        return 2; // Activate failed
    }

    // Try 16-bit PCM format initialization first
    WAVEFORMATEX wfx16 = {};
    wfx16.wFormatTag = WAVE_FORMAT_PCM;
    wfx16.nChannels = static_cast<WORD>(channels);
    wfx16.nSamplesPerSec = static_cast<DWORD>(rate);
    wfx16.wBitsPerSample = 16;
    wfx16.nBlockAlign = static_cast<WORD>(wfx16.nChannels * (wfx16.wBitsPerSample / 8));
    wfx16.nAvgBytesPerSec = wfx16.nSamplesPerSec * wfx16.nBlockAlign;
    wfx16.cbSize = 0;

    bool isFloatFormat = false;
    HRESULT hrInit = audioClient->Initialize(
        AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
        200000, // 20ms in 100ns units
        0,
        &wfx16,
        nullptr
    );

    if (SUCCEEDED(hrInit)) {
        fprintf(stderr, "[AppAudio] Initialized audio client with 16-bit PCM format (%d Hz, %d ch)\n", rate, channels);
        isFloatFormat = false;
    } else {
        fprintf(stderr, "[AppAudio] 16-bit PCM format rejected (0x%08X), trying 32-bit float...\n", hrInit);

        // Re-activate to get a fresh IAudioClient instance
        audioClient.Reset();
        hrAct = ActivateProcessLoopbackClient(pid, includeTree, audioClient);
        if (FAILED(hrAct)) {
            fprintf(stderr, "[AppAudio] Re-activation failed: 0x%08X\n", hrAct);
            CoUninitialize();
            return 2;
        }

        // Try 32-bit float format
        WAVEFORMATEX wfx32 = {};
        wfx32.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
        wfx32.nChannels = static_cast<WORD>(channels);
        wfx32.nSamplesPerSec = static_cast<DWORD>(rate);
        wfx32.wBitsPerSample = 32;
        wfx32.nBlockAlign = static_cast<WORD>(wfx32.nChannels * (wfx32.wBitsPerSample / 8));
        wfx32.nAvgBytesPerSec = wfx32.nSamplesPerSec * wfx32.nBlockAlign;
        wfx32.cbSize = 0;

        HRESULT hrInitFloat = audioClient->Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
            200000, // 20ms
            0,
            &wfx32,
            nullptr
        );

        if (SUCCEEDED(hrInitFloat)) {
            fprintf(stderr, "[AppAudio] Initialized audio client with 32-bit float format (%d Hz, %d ch)\n", rate, channels);
            isFloatFormat = true;
        } else {
            // Try WAVEFORMATEXTENSIBLE with 32-bit float
            audioClient.Reset();
            hrAct = ActivateProcessLoopbackClient(pid, includeTree, audioClient);
            if (SUCCEEDED(hrAct)) {
                WAVEFORMATEXTENSIBLE wfxExt = {};
                wfxExt.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
                wfxExt.Format.nChannels = static_cast<WORD>(channels);
                wfxExt.Format.nSamplesPerSec = static_cast<DWORD>(rate);
                wfxExt.Format.wBitsPerSample = 32;
                wfxExt.Format.nBlockAlign = static_cast<WORD>(wfxExt.Format.nChannels * (wfxExt.Format.wBitsPerSample / 8));
                wfxExt.Format.nAvgBytesPerSec = wfxExt.Format.nSamplesPerSec * wfxExt.Format.nBlockAlign;
                wfxExt.Format.cbSize = sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX);
                wfxExt.Samples.wValidBitsPerSample = 32;
                wfxExt.dwChannelMask = (channels == 2) ? (SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT) : (channels == 1 ? SPEAKER_FRONT_CENTER : 0);
                wfxExt.SubFormat = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT;

                hrInitFloat = audioClient->Initialize(
                    AUDCLNT_SHAREMODE_SHARED,
                    AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                    200000, // 20ms
                    0,
                    &wfxExt.Format,
                    nullptr
                );
                if (SUCCEEDED(hrInitFloat)) {
                    fprintf(stderr, "[AppAudio] Initialized audio client with 32-bit float format (EXTENSIBLE) (%d Hz, %d ch)\n", rate, channels);
                    isFloatFormat = true;
                }
            }

            if (!isFloatFormat) {
                fprintf(stderr, "[AppAudio] IAudioClient::Initialize failed for both 16-bit PCM and 32-bit float: 0x%08X\n", hrInitFloat);
                CoUninitialize();
                return 2;
            }
        }
    }

    HANDLE hAudioEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!hAudioEvent) {
        fprintf(stderr, "[AppAudio] CreateEventW failed\n");
        CoUninitialize();
        return 2;
    }

    HRESULT hrEv = audioClient->SetEventHandle(hAudioEvent);
    if (FAILED(hrEv)) {
        fprintf(stderr, "[AppAudio] SetEventHandle failed: 0x%08X\n", hrEv);
        CloseHandle(hAudioEvent);
        CoUninitialize();
        return 2;
    }

    ComPtr<IAudioCaptureClient> captureClient;
    HRESULT hrSvc = audioClient->GetService(__uuidof(IAudioCaptureClient), &captureClient);
    if (FAILED(hrSvc)) {
        fprintf(stderr, "[AppAudio] GetService(IAudioCaptureClient) failed: 0x%08X\n", hrSvc);
        CloseHandle(hAudioEvent);
        CoUninitialize();
        return 2;
    }

    HRESULT hrStart = audioClient->Start();
    if (FAILED(hrStart)) {
        fprintf(stderr, "[AppAudio] IAudioClient::Start failed: 0x%08X\n", hrStart);
        CloseHandle(hAudioEvent);
        CoUninitialize();
        return 2;
    }

    fprintf(stderr, "[AppAudio] Audio capture started for PID %lu\n", pid);

    // Prepare WAV file stream if --wav is specified
    std::ofstream wavFile;
    uint32_t wavDataBytesWritten = 0;
    if (!wavPath.empty()) {
        wavFile.open(wavPath, std::ios::binary);
        if (!wavFile.is_open()) {
            fprintf(stderr, "[AppAudio] Failed to open WAV file for writing: %s\n", wavPath.c_str());
            audioClient->Stop();
            CloseHandle(hAudioEvent);
            CoUninitialize();
            return 1;
        }

        WavHeader hdr;
        hdr.numChannels = static_cast<uint16_t>(channels);
        hdr.sampleRate = static_cast<uint32_t>(rate);
        hdr.bitsPerSample = 16;
        hdr.blockAlign = static_cast<uint16_t>(channels * 2);
        hdr.byteRate = hdr.sampleRate * hdr.blockAlign;
        hdr.riffSize = 36;
        hdr.dataSize = 0;

        wavFile.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
    } else if (!probe) {
        // Continuous stdout streaming requires binary stdout mode
        _setmode(_fileno(stdout), _O_BINARY);
    }

    uint64_t totalBytesCaptured = 0;
    bool hasNonZeroSample = false;
    auto startTime = std::chrono::steady_clock::now();

    // Main capture loop
    while (true) {
        DWORD waitRes = WaitForSingleObject(hAudioEvent, 200);
        if (waitRes == WAIT_OBJECT_0) {
            UINT32 packetLength = 0;
            HRESULT hrPkt = captureClient->GetNextPacketSize(&packetLength);
            while (SUCCEEDED(hrPkt) && packetLength > 0) {
                BYTE* pData = nullptr;
                UINT32 numFramesToRead = 0;
                DWORD flags = 0;
                UINT64 devPos = 0;
                UINT64 qpcPos = 0;

                HRESULT hrBuf = captureClient->GetBuffer(&pData, &numFramesToRead, &flags, &devPos, &qpcPos);
                if (FAILED(hrBuf)) {
                    // ★失敗時に break しないと、パケットを解放できないまま
                    //   GetNextPacketSize が同じ値を返し続けて無限ループになる。
                    fprintf(stderr, "[AppAudio] GetBuffer failed: 0x%08X\n", hrBuf);
                    break;
                }

                if (numFramesToRead > 0) {
                    size_t sampleCount = static_cast<size_t>(numFramesToRead) * channels;
                    std::vector<int16_t> s16Buf(sampleCount);

                    if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                        std::fill(s16Buf.begin(), s16Buf.end(), static_cast<int16_t>(0));
                    } else {
                        if (isFloatFormat) {
                            const float* floatData = reinterpret_cast<const float*>(pData);
                            for (size_t i = 0; i < sampleCount; ++i) {
                                s16Buf[i] = FloatToS16(floatData[i]);
                                if (s16Buf[i] != 0) {
                                    hasNonZeroSample = true;
                                }
                            }
                        } else {
                            const int16_t* pcmData = reinterpret_cast<const int16_t*>(pData);
                            for (size_t i = 0; i < sampleCount; ++i) {
                                s16Buf[i] = pcmData[i];
                                if (s16Buf[i] != 0) {
                                    hasNonZeroSample = true;
                                }
                            }
                        }
                    }

                    size_t bytesToWrite = sampleCount * sizeof(int16_t);
                    totalBytesCaptured += bytesToWrite;

                    if (!wavPath.empty()) {
                        wavFile.write(reinterpret_cast<const char*>(s16Buf.data()), bytesToWrite);
                        wavDataBytesWritten += static_cast<uint32_t>(bytesToWrite);
                    } else if (!probe) {
                        fwrite(s16Buf.data(), sizeof(int16_t), sampleCount, stdout);
                        fflush(stdout);
                    }
                }

                // ★取得したパケットは 0 フレームでも必ず解放する。
                //   GetBuffer は AUDCLNT_S_BUFFER_EMPTY（成功扱い・0フレーム）を返すことがあり、
                //   そこで解放を飛ばすと GetNextPacketSize が同じ値を返し続けて
                //   内側ループから抜けられなくなる（CPUを焼いたまま --seconds も --probe も効かない）。
                captureClient->ReleaseBuffer(numFramesToRead);

                // ★hrPkt を更新しないと、以降の失敗を検出できないまま
                //   古い成功値で回り続ける。
                hrPkt = captureClient->GetNextPacketSize(&packetLength);
            }
        }

        // TODO(P1): 壁時計基準の無音埋めをここに入れる

        auto now = std::chrono::steady_clock::now();
        auto elapsedSec = std::chrono::duration_cast<std::chrono::seconds>(now - startTime).count();

        if (probe && elapsedSec >= 1) {
            fprintf(stderr, "[AppAudio] Probe result: %llu bytes captured, non-zero sample found: %s\n",
                    totalBytesCaptured, hasNonZeroSample ? "yes" : "no");
            break;
        }

        if (!wavPath.empty() && elapsedSec >= seconds) {
            fprintf(stderr, "[AppAudio] WAV capture finished (%d seconds, %u bytes data)\n", seconds, wavDataBytesWritten);
            break;
        }
    }

    audioClient->Stop();

    // Finalize WAV file header
    if (!wavPath.empty() && wavFile.is_open()) {
        uint32_t riffSize = 36 + wavDataBytesWritten;
        uint32_t dataSize = wavDataBytesWritten;

        wavFile.seekp(4, std::ios::beg);
        wavFile.write(reinterpret_cast<const char*>(&riffSize), sizeof(riffSize));
        wavFile.seekp(40, std::ios::beg);
        wavFile.write(reinterpret_cast<const char*>(&dataSize), sizeof(dataSize));
        wavFile.close();
        fprintf(stderr, "[AppAudio] WAV file closed successfully: %s\n", wavPath.c_str());
    }

    CloseHandle(hAudioEvent);
    CoUninitialize();
    return 0;
}
