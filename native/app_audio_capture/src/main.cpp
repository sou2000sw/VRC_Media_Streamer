// native/app_audio_capture/src/main.cpp
// App Audio Capture Auxiliary Executable (Phase P1)
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
#include <cstdlib>
#include <algorithm>
#include <chrono>
#include <thread>
#include <atomic>
#include <io.h>
#include <fcntl.h>

using Microsoft::WRL::ComPtr;

// 【無音埋め（空振りガード）の設計方針について】
// 当初の想定では「対象が無音の間はパケットが来ないため、壁時計基準で常時無音を生成・埋める必要がある」と考えられていた。
// しかし実測検証の結果、WASAPI Process Loopback APIは対象プロセスが無音であっても無音パケットを正常に供給し続け、
// ドリフトは蓄積しないことが判明した（完全無音30秒で正確に30.000秒のサンプルが供給された）。
// 
// したがって、常時動く壁時計無音生成を入れると二重に無音が埋まり逆に音がズレる原因となるため採用しない。
// 代わりに、デバイス切替や例外的なパケット中断に備えた「空振りガード」として実装する。
// WaitForSingleObjectタイムアウトかつパケットサイズ0の状態が連続して200msを超えた場合に限り、
// 壁時計経過時間に対する不足サンプル数を計算して無音データを補填する。

static std::atomic<bool> g_stopRequested{false};

static BOOL WINAPI ConsoleCtrlHandler(DWORD ctrlType) {
    switch (ctrlType) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
    case CTRL_CLOSE_EVENT:
    case CTRL_LOGOFF_EVENT:
    case CTRL_SHUTDOWN_EVENT:
        g_stopRequested.store(true);
        return TRUE;
    default:
        return FALSE;
    }
}

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

// Helper to set up audio client, capture client, and event handle
static HRESULT SetupAudioCapture(
    DWORD pid,
    bool includeTree,
    int rate,
    int channels,
    ComPtr<IAudioClient>& outAudioClient,
    ComPtr<IAudioCaptureClient>& outCaptureClient,
    HANDLE& outEventHandle,
    bool& outIsFloatFormat
) {
    ComPtr<IAudioClient> audioClient;
    HRESULT hrAct = ActivateProcessLoopbackClient(pid, includeTree, audioClient);
    if (FAILED(hrAct)) {
        fprintf(stderr, "[AppAudio] ActivateProcessLoopbackClient failed: 0x%08X\n", hrAct);
        return hrAct;
    }

    WAVEFORMATEX wfx16 = {};
    wfx16.wFormatTag = WAVE_FORMAT_PCM;
    wfx16.nChannels = static_cast<WORD>(channels);
    wfx16.nSamplesPerSec = static_cast<DWORD>(rate);
    wfx16.wBitsPerSample = 16;
    wfx16.nBlockAlign = static_cast<WORD>(wfx16.nChannels * (wfx16.wBitsPerSample / 8));
    wfx16.nAvgBytesPerSec = wfx16.nSamplesPerSec * wfx16.nBlockAlign;
    wfx16.cbSize = 0;

    bool isFloat = false;
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
        isFloat = false;
    } else {
        fprintf(stderr, "[AppAudio] 16-bit PCM format rejected (0x%08X), trying 32-bit float...\n", hrInit);
        audioClient.Reset();
        hrAct = ActivateProcessLoopbackClient(pid, includeTree, audioClient);
        if (FAILED(hrAct)) {
            fprintf(stderr, "[AppAudio] Re-activation failed: 0x%08X\n", hrAct);
            return hrAct;
        }

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
            200000,
            0,
            &wfx32,
            nullptr
        );

        if (SUCCEEDED(hrInitFloat)) {
            fprintf(stderr, "[AppAudio] Initialized audio client with 32-bit float format (%d Hz, %d ch)\n", rate, channels);
            isFloat = true;
        } else {
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
                    200000,
                    0,
                    &wfxExt.Format,
                    nullptr
                );
                if (SUCCEEDED(hrInitFloat)) {
                    fprintf(stderr, "[AppAudio] Initialized audio client with 32-bit float format (EXTENSIBLE) (%d Hz, %d ch)\n", rate, channels);
                    isFloat = true;
                }
            }

            if (!isFloat) {
                fprintf(stderr, "[AppAudio] IAudioClient::Initialize failed for both PCM and Float: 0x%08X\n", hrInitFloat);
                return hrInitFloat;
            }
        }
    }

    HANDLE hEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!hEvent) {
        fprintf(stderr, "[AppAudio] CreateEventW failed\n");
        return E_FAIL;
    }

    HRESULT hrEv = audioClient->SetEventHandle(hEvent);
    if (FAILED(hrEv)) {
        fprintf(stderr, "[AppAudio] SetEventHandle failed: 0x%08X\n", hrEv);
        CloseHandle(hEvent);
        return hrEv;
    }

    ComPtr<IAudioCaptureClient> captureClient;
    HRESULT hrSvc = audioClient->GetService(__uuidof(IAudioCaptureClient), &captureClient);
    if (FAILED(hrSvc)) {
        fprintf(stderr, "[AppAudio] GetService(IAudioCaptureClient) failed: 0x%08X\n", hrSvc);
        CloseHandle(hEvent);
        return hrSvc;
    }

    HRESULT hrStart = audioClient->Start();
    if (FAILED(hrStart)) {
        fprintf(stderr, "[AppAudio] IAudioClient::Start failed: 0x%08X\n", hrStart);
        CloseHandle(hEvent);
        return hrStart;
    }

    outAudioClient = audioClient;
    outCaptureClient = captureClient;
    outEventHandle = hEvent;
    outIsFloatFormat = isFloat;

    return S_OK;
}

// Write 16-bit PCM buffer to WAV or stdout
static bool WritePCMData(
    const int16_t* pcmBuf,
    size_t sampleCount,
    const std::string& wavPath,
    std::ofstream& wavFile,
    uint32_t& wavDataBytesWritten,
    bool probe
) {
    if (sampleCount == 0) return true;
    size_t bytes = sampleCount * sizeof(int16_t);
    if (!wavPath.empty() && wavFile.is_open()) {
        wavFile.write(reinterpret_cast<const char*>(pcmBuf), bytes);
        wavDataBytesWritten += static_cast<uint32_t>(bytes);
    } else if (!probe) {
        size_t written = fwrite(pcmBuf, sizeof(int16_t), sampleCount, stdout);
        fflush(stdout);
        if (written < sampleCount) {
            return false; // Downstream pipe closed
        }
    }
    return true;
}

int main(int argc, char* argv[]) {
    SetConsoleCtrlHandler(ConsoleCtrlHandler, TRUE);

    DWORD pid = 0;
    bool includeTree = true;
    int rate = 48000;
    int channels = 2;
    std::string wavPath;
    int seconds = -1; // -1 indicates not specified by user
    bool probe = false;
    bool stopOnExit = false;
    int statsInterval = 0;

    int levelIntervalMs = 0;
    DWORD parentPid = 0;
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
        } else if (arg == "--stop-on-exit") {
            stopOnExit = true;
        } else if (arg == "--parent-pid" && i + 1 < argc) {
            // 親（本体アプリ）のPID。親が消えたら自分も終わる。
            // ★これが無いと、本体をタスクマネージャ等で強制終了したとき、
            //   この exe だけが残って音声を取り込み続ける。実際に2回発生した。
            parentPid = static_cast<DWORD>(std::strtoul(argv[++i], nullptr, 10));
        } else if (arg == "--level" && i + 1 < argc) {
            // 入力レベルの通知間隔[ms]。0で無効。
            // ★UIのゲージ用。取り込めているのかを配信中に目で確かめられるようにする。
            levelIntervalMs = std::atoi(argv[++i]);
        } else if (arg == "--stats" && i + 1 < argc) {
            statsInterval = std::stoi(argv[++i]);
        } else {
            fprintf(stderr, "[AppAudio] Unknown or invalid argument: %s\n", arg.c_str());
            return 1;
        }
    }

    if (pid == 0) {
        fprintf(stderr, "[AppAudio] Missing required argument: --pid <PID>\n");
        return 1;
    }

    // Default --seconds rules (Section 3.1):
    // If --wav is specified and --seconds was not passed, default to 10.
    // If streaming (no --wav, no --probe) and --seconds was not passed, default to 0 (indefinite).
    if (seconds < 0) {
        if (!wavPath.empty()) {
            seconds = 10;
        } else {
            seconds = 0;
        }
    }

    // Exit code 3 if target process does not exist at startup
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
    ComPtr<IAudioCaptureClient> captureClient;
    HANDLE hAudioEvent = nullptr;
    bool isFloatFormat = false;

    HRESULT hrSetup = SetupAudioCapture(pid, includeTree, rate, channels, audioClient, captureClient, hAudioEvent, isFloatFormat);
    if (FAILED(hrSetup)) {
        if (hrSetup == E_NOTIMPL || hrSetup == E_NOINTERFACE || hrSetup == HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED)) {
            CoUninitialize();
            return 4; // OS not supported
        }
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

    // Capture loop state variables
    uint64_t totalBytesCaptured = 0;
    uint64_t totalProducedFrames = 0;
    uint64_t totalSilenceFilledFrames = 0;
    // 入力レベル集計（--level 用）。区間ごとに peak と RMS を出して、そのつど捨てる。
    double levelSumSq = 0.0;
    uint64_t levelSampleCount = 0;
    int levelPeakAbs = 0;
    bool hasNonZeroSample = false;
    int exitCode = 0;
    bool targetExitLogged = false;

    // ★親のハンドルは起動時に1度だけ開いて持ち続ける。毎回PIDで開き直すと、
    //   親が終了したあとに同じPIDが別プロセスへ再利用された場合に生存と誤判定する。
    HANDLE hParent = NULL;
    if (parentPid != 0) {
        hParent = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                              FALSE, parentPid);
        if (hParent == NULL) {
            DWORD err = GetLastError();
            if (err == ERROR_ACCESS_DENIED) {
                // 監視はできないが、動作そのものは続けられる。
                fprintf(stderr, "[AppAudio] Parent %lu: access denied, "
                                "parent monitoring disabled\n", parentPid);
            } else {
                fprintf(stderr, "[AppAudio] Parent %lu is already gone, exiting\n", parentPid);
                if (audioClient) audioClient->Stop();
                CoUninitialize();
                return 0;
            }
        } else {
            fprintf(stderr, "[AppAudio] Watching parent process %lu\n", parentPid);
        }
    }

    auto startTime = std::chrono::steady_clock::now();
    auto lastPacketOrGuardTime = startTime;
    auto lastProcCheckTime = startTime;
    auto lastStatsTime = startTime;
    auto lastLevelTime = lastStatsTime;

    // Main capture loop
    while (!g_stopRequested.load()) {
        auto now = std::chrono::steady_clock::now();

        // Check target process status once per second
        if (now - lastProcCheckTime >= std::chrono::seconds(1)) {
            lastProcCheckTime = now;

            // 親が消えていたら、こちらも畳む。対象プロセスの生死とは無関係に、
            // 本体が居なくなった時点でこの exe の存在意義が無くなるため。
            if (hParent != NULL && WaitForSingleObject(hParent, 0) == WAIT_OBJECT_0) {
                fprintf(stderr, "[AppAudio] Parent process %lu exited, stopping\n", parentPid);
                exitCode = 0;
                break;
            }
            if (!ProcessExists(pid)) {
                if (stopOnExit) {
                    fprintf(stderr, "[AppAudio] Target process %lu exited (--stop-on-exit specified), stopping\n", pid);
                    exitCode = 3;
                    break;
                } else if (!targetExitLogged) {
                    fprintf(stderr, "[AppAudio] Target process %lu has exited, continuing capture with silence...\n", pid);
                    targetExitLogged = true;
                }
            }
        }

        // 入力レベルの通知（UIのゲージ用）
        if (levelIntervalMs > 0 &&
            std::chrono::duration_cast<std::chrono::milliseconds>(now - lastLevelTime).count() >= levelIntervalMs) {
            lastLevelTime = now;
            double rms = 0.0;
            if (levelSampleCount > 0) {
                rms = std::sqrt(levelSumSq / static_cast<double>(levelSampleCount));
            }
            double peak = static_cast<double>(levelPeakAbs) / 32768.0;
            fprintf(stderr, "[AppAudio] level peak=%.5f rms=%.5f\n", peak, rms);
            fflush(stderr);
            levelSumSq = 0.0;
            levelSampleCount = 0;
            levelPeakAbs = 0;
        }

        // Stats output (Section 3.5)
        if (statsInterval > 0 && (now - lastStatsTime) >= std::chrono::seconds(statsInterval)) {
            lastStatsTime = now;
            double producedSec = static_cast<double>(totalProducedFrames) / rate;
            double elapsedSec = std::chrono::duration<double>(now - startTime).count();
            long long driftMs = static_cast<long long>(std::round((producedSec - elapsedSec) * 1000.0));
            long long silenceFilledMs = static_cast<long long>(std::round((static_cast<double>(totalSilenceFilledFrames) / rate) * 1000.0));

            fprintf(stderr, "[AppAudio] stats: produced=%.2fs elapsed=%.2fs drift=%lldms silence_filled=%lldms\n",
                    producedSec, elapsedSec, driftMs, silenceFilledMs);
        }

        DWORD waitRes = WaitForSingleObject(hAudioEvent, 50);
        bool gotPackets = false;
        bool deviceInvalidated = false;

        if (waitRes == WAIT_OBJECT_0) {
            UINT32 packetLength = 0;
            HRESULT hrPkt = captureClient->GetNextPacketSize(&packetLength);

            if (hrPkt == AUDCLNT_E_DEVICE_INVALIDATED) {
                deviceInvalidated = true;
            } else {
                while (SUCCEEDED(hrPkt) && packetLength > 0) {
                    BYTE* pData = nullptr;
                    UINT32 numFramesToRead = 0;
                    DWORD flags = 0;
                    UINT64 devPos = 0;
                    UINT64 qpcPos = 0;

                    HRESULT hrBuf = captureClient->GetBuffer(&pData, &numFramesToRead, &flags, &devPos, &qpcPos);
                    if (hrBuf == AUDCLNT_E_DEVICE_INVALIDATED) {
                        deviceInvalidated = true;
                        break;
                    }
                    if (FAILED(hrBuf)) {
                        fprintf(stderr, "[AppAudio] GetBuffer failed: 0x%08X\n", hrBuf);
                        break;
                    }

                    if (numFramesToRead > 0) {
                        gotPackets = true;
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
                        totalProducedFrames += numFramesToRead;

                        // ★レベル集計は無音パケットも必ず含める。含めないと、鳴り止んだ
                        //   ときにゲージが最後の値のまま張り付いて「入力できている」と
                        //   誤読させてしまう。
                        if (levelIntervalMs > 0) {
                            for (size_t i = 0; i < sampleCount; ++i) {
                                int v = s16Buf[i];
                                int a = (v < 0) ? -v : v;
                                if (a > levelPeakAbs) levelPeakAbs = a;
                                double f = static_cast<double>(v) / 32768.0;
                                levelSumSq += f * f;
                            }
                            levelSampleCount += sampleCount;
                        }

                        if (!WritePCMData(s16Buf.data(), sampleCount, wavPath, wavFile, wavDataBytesWritten, probe)) {
                            fprintf(stderr, "[AppAudio] stdout write failed or pipe closed by downstream, exiting cleanly\n");
                            exitCode = 0;
                            g_stopRequested.store(true);
                            break;
                        }
                    }

                    captureClient->ReleaseBuffer(numFramesToRead);
                    hrPkt = captureClient->GetNextPacketSize(&packetLength);
                    if (hrPkt == AUDCLNT_E_DEVICE_INVALIDATED) {
                        deviceInvalidated = true;
                        break;
                    }
                }
            }
        }

        if (g_stopRequested.load()) {
            break;
        }

        // Handle Device Invalidation (Section 3.4)
        if (deviceInvalidated) {
            fprintf(stderr, "[AppAudio] Device invalidated (AUDCLNT_E_DEVICE_INVALIDATED), attempting re-activation...\n");

            if (hAudioEvent) {
                CloseHandle(hAudioEvent);
                hAudioEvent = nullptr;
            }
            audioClient.Reset();
            captureClient.Reset();

            bool reconfigOk = false;
            for (int attempt = 1; attempt <= 5; ++attempt) {
                if (g_stopRequested.load()) break;

                fprintf(stderr, "[AppAudio] Device re-activation attempt %d/5...\n", attempt);

                // Output 1 second of silence while waiting (10 x 100ms chunks)
                for (int s = 0; s < 10; ++s) {
                    if (g_stopRequested.load()) break;
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));

                    size_t silenceFrames = rate / 10;
                    size_t silenceSamples = silenceFrames * channels;
                    std::vector<int16_t> silenceBuf(silenceSamples, 0);

                    totalProducedFrames += silenceFrames;
                    totalSilenceFilledFrames += silenceFrames;

                    if (!WritePCMData(silenceBuf.data(), silenceSamples, wavPath, wavFile, wavDataBytesWritten, probe)) {
                        fprintf(stderr, "[AppAudio] stdout pipe closed during device re-activation, exiting cleanly\n");
                        exitCode = 0;
                        g_stopRequested.store(true);
                        break;
                    }
                }

                if (g_stopRequested.load()) break;

                HRESULT hrRetry = SetupAudioCapture(pid, includeTree, rate, channels, audioClient, captureClient, hAudioEvent, isFloatFormat);
                if (SUCCEEDED(hrRetry)) {
                    fprintf(stderr, "[AppAudio] Re-activated audio client successfully on attempt %d\n", attempt);
                    reconfigOk = true;
                    lastPacketOrGuardTime = std::chrono::steady_clock::now();
                    break;
                } else {
                    fprintf(stderr, "[AppAudio] Re-activation attempt %d failed: 0x%08X\n", attempt, hrRetry);
                }
            }

            if (!reconfigOk && !g_stopRequested.load()) {
                fprintf(stderr, "[AppAudio] Device re-activation failed after 5 attempts, exiting with code 2\n");
                exitCode = 2;
                break;
            }
            continue;
        }

        now = std::chrono::steady_clock::now();
        if (gotPackets) {
            lastPacketOrGuardTime = now;
        } else {
            // Silence Guard ("空振りガード", Section 2)
            // When WaitForSingleObject times out or GetNextPacketSize is 0 continuously for > 200ms:
            auto emptyMs = std::chrono::duration_cast<std::chrono::milliseconds>(now - lastPacketOrGuardTime).count();
            if (emptyMs >= 200) {
                double elapsedSec = std::chrono::duration<double>(now - startTime).count();
                uint64_t expectedFrames = static_cast<uint64_t>(elapsedSec * rate);

                if (expectedFrames > totalProducedFrames) {
                    uint64_t missingFrames = expectedFrames - totalProducedFrames;
                    size_t silenceSamples = static_cast<size_t>(missingFrames) * channels;
                    std::vector<int16_t> silenceBuf(silenceSamples, 0);

                    totalProducedFrames += missingFrames;
                    totalSilenceFilledFrames += missingFrames;

                    if (!WritePCMData(silenceBuf.data(), silenceSamples, wavPath, wavFile, wavDataBytesWritten, probe)) {
                        fprintf(stderr, "[AppAudio] stdout pipe closed during silence fill, exiting cleanly\n");
                        exitCode = 0;
                        g_stopRequested.store(true);
                        break;
                    }

                    double filledMs = (static_cast<double>(missingFrames) / rate) * 1000.0;
                    double totalFilledSec = static_cast<double>(totalSilenceFilledFrames) / rate;

                    fprintf(stderr, "[AppAudio] silence guard filled %.0f ms (total %.1f s)\n", filledMs, totalFilledSec);
                }

                lastPacketOrGuardTime = now;
            }
        }

        // Check completion criteria (--seconds or --probe)
        double elapsedSec = std::chrono::duration<double>(now - startTime).count();

        if (probe && elapsedSec >= 1.0) {
            fprintf(stderr, "[AppAudio] Probe result: %llu bytes captured, non-zero sample found: %s\n",
                    totalBytesCaptured, hasNonZeroSample ? "yes" : "no");
            break;
        }

        if (seconds > 0 && elapsedSec >= static_cast<double>(seconds)) {
            if (!wavPath.empty()) {
                fprintf(stderr, "[AppAudio] WAV capture finished (%d seconds, %u bytes data)\n", seconds, wavDataBytesWritten);
            } else {
                fprintf(stderr, "[AppAudio] Stream capture finished (%d seconds)\n", seconds);
            }
            break;
        }
    }

    // Clean up audio resources
    if (audioClient) {
        audioClient->Stop();
    }

    // Finalize WAV file header if writing WAV
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

    if (hAudioEvent) {
        CloseHandle(hAudioEvent);
    }
    CoUninitialize();

    if (hParent != NULL) {
        CloseHandle(hParent);
        hParent = NULL;
    }

    // Summary of silence guard (Section 2)
    double totalFilledSec = static_cast<double>(totalSilenceFilledFrames) / rate;
    fprintf(stderr, "[AppAudio] Silence guard summary: filled total %.2f s of silence\n", totalFilledSec);

    return exitCode;
}
