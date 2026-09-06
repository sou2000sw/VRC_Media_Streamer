// native/window_capture/src/main.cpp
// タスク26: ウィンドウ単位キャプチャ補助exe（Windows.Graphics.Capture）
//
// 指定した HWND のウィンドウの中身だけを取り込み、生BGRAフレームを
// 名前付きパイプ（本番）またはファイル（検証）へ一定間隔で吐き続ける。
// **手前に重なった別ウィンドウが映らないこと**が全目的。
//
// 設計の正本: docs/TASK26_ウィンドウ単位キャプチャ_設計.md

#include <windows.h>
#include <d3d11_4.h>   // ID3D11Multithread は d3d11.h ではなくこちら
#include <dxgi.h>
#include <inspectable.h>

#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>

#include <winrt/base.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <winrt/Windows.Security.Authorization.AppCapabilityAccess.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#pragma comment(lib, "windowsapp.lib")
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "winmm.lib")

namespace wgc = winrt::Windows::Graphics::Capture;
namespace wgdx = winrt::Windows::Graphics::DirectX;
namespace wgd3d = winrt::Windows::Graphics::DirectX::Direct3D11;

// ---------------------------------------------------------------------------
// 終了コード（docs/TASK26 の契約と一致させること）
// ---------------------------------------------------------------------------
static const int EXIT_OK           = 0;
static const int EXIT_BAD_ARGS     = 2;
static const int EXIT_NO_WGC       = 3;
static const int EXIT_BAD_WINDOW   = 4;
static const int EXIT_SINK_FAILED  = 5;

// ---------------------------------------------------------------------------
// グローバル状態
// ---------------------------------------------------------------------------
static std::atomic<bool> g_stop{false};
static std::atomic<int>  g_exitCode{EXIT_OK};
static const char*       g_exitReason = "normal";

static std::mutex            g_frameMutex;
static std::vector<uint8_t>  g_latest;       // FrameArrived が書く（要ロック）
static std::atomic<uint64_t> g_latestSeq{0}; // 更新のたびに増える

static std::atomic<uint64_t> g_statSent{0};
static std::atomic<uint64_t> g_statDup{0};
static std::atomic<uint64_t> g_statResize{0};

static int g_outW = 0;   // 出力寸法。確定後は絶対に変えない
static int g_outH = 0;

static winrt::com_ptr<ID3D11Device>        g_d3dDevice;
static winrt::com_ptr<ID3D11DeviceContext> g_d3dContext;
static winrt::com_ptr<ID3D11Texture2D>     g_staging;
static int g_stagingW = 0;
static int g_stagingH = 0;

static void RequestStop(int code, const char* reason) {
    int expected = EXIT_OK;
    // 先に立った理由を優先する（後から来る「正常終了」で上書きしない）
    if (code != EXIT_OK) {
        g_exitCode.compare_exchange_strong(expected, code);
        if (expected == EXIT_OK) {
            g_exitReason = reason;
        }
    }
    g_stop.store(true);
}

static BOOL WINAPI ConsoleCtrlHandler(DWORD ctrlType) {
    switch (ctrlType) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
    case CTRL_CLOSE_EVENT:
    case CTRL_LOGOFF_EVENT:
    case CTRL_SHUTDOWN_EVENT:
        RequestStop(EXIT_OK, "ctrl-event");
        return TRUE;
    default:
        return FALSE;
    }
}

static void LogLine(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    fflush(stderr);
}

// ---------------------------------------------------------------------------
// 出力先（名前付きパイプ / ファイル）
// ---------------------------------------------------------------------------
class Sink {
public:
    ~Sink() { Close(); }

    // 名前付きパイプのサーバ側を作る。まだ接続は待たない。
    bool CreatePipe(const std::wstring& name) {
        m_overlapped = true;
        m_handle = ::CreateNamedPipeW(
            name.c_str(),
            PIPE_ACCESS_OUTBOUND | FILE_FLAG_OVERLAPPED,
            PIPE_TYPE_BYTE | PIPE_WAIT,
            1,                    // 読み手は ffmpeg ひとつだけ
            8u << 20, 8u << 20,   // out/in バッファ 8MB
            0, nullptr);
        if (m_handle == INVALID_HANDLE_VALUE) {
            LogLine("[wincap] CreateNamedPipeW failed err=%lu", ::GetLastError());
            m_handle = nullptr;
            return false;
        }
        m_event = ::CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!m_event) {
            LogLine("[wincap] CreateEvent failed err=%lu", ::GetLastError());
            return false;
        }
        return true;
    }

    // 読み手（ffmpeg）の接続を待つ。timeoutSec 以内に来なければ false。
    bool WaitForClient(int timeoutSec) {
        OVERLAPPED ov{};
        ::ResetEvent(m_event);
        ov.hEvent = m_event;
        if (::ConnectNamedPipe(m_handle, &ov)) {
            return true;
        }
        DWORD err = ::GetLastError();
        if (err == ERROR_PIPE_CONNECTED) {
            return true;   // 待つ前に既に繋がっていた。成功として扱う
        }
        if (err != ERROR_IO_PENDING) {
            LogLine("[wincap] ConnectNamedPipe failed err=%lu", err);
            return false;
        }
        const DWORD deadlineMs = (timeoutSec > 0)
            ? static_cast<DWORD>(timeoutSec) * 1000u : INFINITE;
        DWORD waited = 0;
        for (;;) {
            DWORD slice = 250;
            DWORD r = ::WaitForSingleObject(m_event, slice);
            if (r == WAIT_OBJECT_0) {
                DWORD dummy = 0;
                return ::GetOverlappedResult(m_handle, &ov, &dummy, FALSE) != 0;
            }
            if (g_stop.load()) {
                ::CancelIoEx(m_handle, &ov);
                return false;
            }
            waited += slice;
            if (deadlineMs != INFINITE && waited >= deadlineMs) {
                ::CancelIoEx(m_handle, &ov);
                LogLine("[wincap] no reader connected within %ds", timeoutSec);
                return false;
            }
        }
    }

    bool CreateOutFile(const std::wstring& path) {
        m_overlapped = false;
        m_handle = ::CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ,
                                 nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (m_handle == INVALID_HANDLE_VALUE) {
            LogLine("[wincap] CreateFileW failed err=%lu", ::GetLastError());
            m_handle = nullptr;
            return false;
        }
        return true;
    }

    // 全バイト書き切るまで回す。読み手が消えたら false（異常ではない）。
    bool WriteAll(const uint8_t* data, size_t len) {
        size_t done = 0;
        while (done < len) {
            const DWORD chunk = static_cast<DWORD>(
                (len - done > 0x10000000u) ? 0x10000000u : (len - done));
            DWORD written = 0;
            if (!m_overlapped) {
                if (!::WriteFile(m_handle, data + done, chunk, &written, nullptr)) {
                    return false;
                }
            } else {
                OVERLAPPED ov{};
                ::ResetEvent(m_event);
                ov.hEvent = m_event;
                if (!::WriteFile(m_handle, data + done, chunk, nullptr, &ov)) {
                    DWORD err = ::GetLastError();
                    if (err != ERROR_IO_PENDING) {
                        return false;
                    }
                    for (;;) {
                        DWORD r = ::WaitForSingleObject(m_event, 250);
                        if (r == WAIT_OBJECT_0) break;
                        if (g_stop.load()) {
                            ::CancelIoEx(m_handle, &ov);
                            return false;
                        }
                    }
                }
                if (!::GetOverlappedResult(m_handle, &ov, &written, FALSE)) {
                    return false;
                }
            }
            if (written == 0) {
                return false;
            }
            done += written;
        }
        return true;
    }

    void Close() {
        if (m_handle) {
            if (m_overlapped) {
                ::FlushFileBuffers(m_handle);
                ::DisconnectNamedPipe(m_handle);
            }
            ::CloseHandle(m_handle);
            m_handle = nullptr;
        }
        if (m_event) {
            ::CloseHandle(m_event);
            m_event = nullptr;
        }
    }

private:
    HANDLE m_handle = nullptr;
    HANDLE m_event = nullptr;
    bool   m_overlapped = false;
};

// ---------------------------------------------------------------------------
// D3D11 / WinRT の相互運用
// ---------------------------------------------------------------------------
static wgd3d::IDirect3DDevice CreateWinRTDevice(ID3D11Device* device) {
    winrt::com_ptr<IDXGIDevice> dxgiDevice;
    winrt::check_hresult(device->QueryInterface(winrt::guid_of<IDXGIDevice>(),
                                                dxgiDevice.put_void()));
    winrt::com_ptr<::IInspectable> inspectable;
    winrt::check_hresult(
        ::CreateDirect3D11DeviceFromDXGIDevice(dxgiDevice.get(), inspectable.put()));
    return inspectable.as<wgd3d::IDirect3DDevice>();
}

static winrt::com_ptr<ID3D11Texture2D> GetTextureFromSurface(
        wgd3d::IDirect3DSurface const& surface) {
    auto access = surface.as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
    winrt::com_ptr<ID3D11Texture2D> texture;
    winrt::check_hresult(access->GetInterface(winrt::guid_of<ID3D11Texture2D>(),
                                              texture.put_void()));
    return texture;
}

// ---------------------------------------------------------------------------
// フレーム取り込み
// ---------------------------------------------------------------------------
// ★中央寄せの切り貼りだけを行う。拡大縮小（リサンプル）は絶対にしない。
//   最終的な寸法合わせは下流の ffmpeg の scale+pad が行う。
static void BlitCenter(const uint8_t* src, int srcStride, int srcW, int srcH,
                       std::vector<uint8_t>& dst, int dstW, int dstH) {
    const int copyW = (srcW < dstW) ? srcW : dstW;
    const int copyH = (srcH < dstH) ? srcH : dstH;
    if (copyW <= 0 || copyH <= 0) {
        return;
    }
    // 全面を覆えないときだけ黒で埋め直す（毎フレームの memset を避ける）
    if (copyW != dstW || copyH != dstH) {
        for (size_t i = 0; i < dst.size(); i += 4) {
            dst[i + 0] = 0; dst[i + 1] = 0; dst[i + 2] = 0; dst[i + 3] = 255;
        }
    }
    const int srcX = (srcW - copyW) / 2;
    const int srcY = (srcH - copyH) / 2;
    const int dstX = (dstW - copyW) / 2;
    const int dstY = (dstH - copyH) / 2;
    const size_t rowBytes = static_cast<size_t>(copyW) * 4;
    for (int y = 0; y < copyH; ++y) {
        const uint8_t* s = src + static_cast<size_t>(srcY + y) * srcStride
                               + static_cast<size_t>(srcX) * 4;
        uint8_t* d = dst.data() + (static_cast<size_t>(dstY + y) * dstW
                                   + static_cast<size_t>(dstX)) * 4;
        memcpy(d, s, rowBytes);
    }
}

static bool EnsureStaging(int w, int h, DXGI_FORMAT format) {
    if (g_staging && g_stagingW == w && g_stagingH == h) {
        return true;
    }
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = static_cast<UINT>(w);
    desc.Height = static_cast<UINT>(h);
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = format;
    desc.SampleDesc.Count = 1;
    desc.SampleDesc.Quality = 0;
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    desc.MiscFlags = 0;

    winrt::com_ptr<ID3D11Texture2D> tex;
    HRESULT hr = g_d3dDevice->CreateTexture2D(&desc, nullptr, tex.put());
    if (FAILED(hr)) {
        LogLine("[wincap] CreateTexture2D(staging) failed hr=0x%08lX",
                static_cast<unsigned long>(hr));
        return false;
    }
    g_staging = tex;
    g_stagingW = w;
    g_stagingH = h;
    return true;
}

// ---------------------------------------------------------------------------
// 引数
// ---------------------------------------------------------------------------
struct Options {
    HWND        hwnd = nullptr;
    std::wstring pipeName;
    std::wstring outFile;
    int  fps = 30;
    bool drawMouse = true;
    bool noBorder = true;
    DWORD parentPid = 0;
    int  statsSec = 0;
    int  durationSec = 0;
    int  connectTimeoutSec = 15;
};

static void PrintUsage() {
    LogLine("usage: window_capture.exe --hwnd <N> (--pipe <name> | --out-file <path>)");
    LogLine("       [--fps 30] [--draw-mouse 0|1] [--no-border 0|1]");
    LogLine("       [--parent-pid N] [--stats SEC] [--duration SEC]");
    LogLine("       [--connect-timeout 15]");
}

static bool ParseBool(const wchar_t* v, bool& out) {
    if (!v) return false;
    if (!wcscmp(v, L"1") || !_wcsicmp(v, L"true"))  { out = true;  return true; }
    if (!wcscmp(v, L"0") || !_wcsicmp(v, L"false")) { out = false; return true; }
    return false;
}

static bool ParseArgs(int argc, wchar_t** argv, Options& o) {
    for (int i = 1; i < argc; ++i) {
        const wchar_t* a = argv[i];
        const wchar_t* v = (i + 1 < argc) ? argv[i + 1] : nullptr;
        auto need = [&](void) -> bool {
            if (!v) { LogLine("[wincap] missing value after an option"); return false; }
            ++i; return true;
        };
        if (!wcscmp(a, L"--hwnd")) {
            if (!need()) return false;
            o.hwnd = reinterpret_cast<HWND>(static_cast<uintptr_t>(_wcstoui64(v, nullptr, 10)));
        } else if (!wcscmp(a, L"--pipe")) {
            if (!need()) return false;
            o.pipeName = v;
        } else if (!wcscmp(a, L"--out-file")) {
            if (!need()) return false;
            o.outFile = v;
        } else if (!wcscmp(a, L"--fps")) {
            if (!need()) return false;
            o.fps = _wtoi(v);
        } else if (!wcscmp(a, L"--draw-mouse")) {
            if (!need()) return false;
            if (!ParseBool(v, o.drawMouse)) return false;
        } else if (!wcscmp(a, L"--no-border")) {
            if (!need()) return false;
            if (!ParseBool(v, o.noBorder)) return false;
        } else if (!wcscmp(a, L"--parent-pid")) {
            if (!need()) return false;
            o.parentPid = static_cast<DWORD>(_wtoi64(v));
        } else if (!wcscmp(a, L"--stats")) {
            if (!need()) return false;
            o.statsSec = _wtoi(v);
        } else if (!wcscmp(a, L"--duration")) {
            if (!need()) return false;
            o.durationSec = _wtoi(v);
        } else if (!wcscmp(a, L"--connect-timeout")) {
            if (!need()) return false;
            o.connectTimeoutSec = _wtoi(v);
        } else {
            LogLine("[wincap] unknown argument");
            return false;
        }
    }
    if (!o.hwnd) {
        LogLine("[wincap] --hwnd is required");
        return false;
    }
    if (o.pipeName.empty() == o.outFile.empty()) {
        LogLine("[wincap] exactly one of --pipe / --out-file is required");
        return false;
    }
    if (o.fps < 1) o.fps = 1;
    if (o.fps > 60) o.fps = 60;
    if (!o.pipeName.empty() && o.pipeName.rfind(L"\\\\.\\pipe\\", 0) != 0) {
        o.pipeName = L"\\\\.\\pipe\\" + o.pipeName;
    }
    return true;
}

// ---------------------------------------------------------------------------
// 親プロセスの死活監視
// ---------------------------------------------------------------------------
// ★これは必須。同型の補助exeで、本体が強制終了された際に補助exeだけが
//   残って動き続ける事故が実際に2回起きている。
static void ParentWatchdog(DWORD parentPid) {
    while (!g_stop.load()) {
        HANDLE h = ::OpenProcess(SYNCHRONIZE, FALSE, parentPid);
        if (!h) {
            LogLine("[wincap] parent process is gone -> stopping");
            RequestStop(EXIT_OK, "parent-gone");
            return;
        }
        DWORD r = ::WaitForSingleObject(h, 1000);
        ::CloseHandle(h);
        if (r == WAIT_OBJECT_0) {
            LogLine("[wincap] parent process exited -> stopping");
            RequestStop(EXIT_OK, "parent-exit");
            return;
        }
    }
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
int wmain(int argc, wchar_t** argv) {
    Options opt;
    if (!ParseArgs(argc, argv, opt)) {
        PrintUsage();
        return EXIT_BAD_ARGS;
    }

    ::SetConsoleCtrlHandler(ConsoleCtrlHandler, TRUE);
    ::timeBeginPeriod(1);

    int rc = EXIT_OK;
    Sink sink;
    wgc::GraphicsCaptureSession session{nullptr};
    wgc::Direct3D11CaptureFramePool framePool{nullptr};
    std::thread writer;
    std::thread watchdog;

    try {
        winrt::init_apartment(winrt::apartment_type::multi_threaded);

        if (!wgc::GraphicsCaptureSession::IsSupported()) {
            LogLine("[wincap] Windows.Graphics.Capture is not supported on this system");
            ::timeEndPeriod(1);
            return EXIT_NO_WGC;
        }

        // --- D3D11 デバイス（ハードウェア → 駄目なら WARP）---
        const D3D_FEATURE_LEVEL levels[] = {
            D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0,
            D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0,
        };
        HRESULT hr = ::D3D11CreateDevice(
            nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, ARRAYSIZE(levels),
            D3D11_SDK_VERSION, g_d3dDevice.put(), nullptr, g_d3dContext.put());
        if (FAILED(hr)) {
            LogLine("[wincap] hardware D3D11 device failed hr=0x%08lX -> trying WARP",
                    static_cast<unsigned long>(hr));
            hr = ::D3D11CreateDevice(
                nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
                D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, ARRAYSIZE(levels),
                D3D11_SDK_VERSION, g_d3dDevice.put(), nullptr, g_d3dContext.put());
        }
        if (FAILED(hr)) {
            LogLine("[wincap] D3D11CreateDevice failed hr=0x%08lX",
                    static_cast<unsigned long>(hr));
            ::timeEndPeriod(1);
            return EXIT_NO_WGC;
        }
        // FrameArrived はスレッドプールから来るので、コンテキストを保護する
        {
            winrt::com_ptr<ID3D11Multithread> mt;
            if (SUCCEEDED(g_d3dContext->QueryInterface(winrt::guid_of<ID3D11Multithread>(),
                                                       mt.put_void()))) {
                mt->SetMultithreadProtected(TRUE);
            }
        }
        auto winrtDevice = CreateWinRTDevice(g_d3dDevice.get());

        // --- HWND から GraphicsCaptureItem ---
        if (!::IsWindow(opt.hwnd)) {
            LogLine("[wincap] invalid window handle");
            ::timeEndPeriod(1);
            return EXIT_BAD_WINDOW;
        }
        wgc::GraphicsCaptureItem item{nullptr};
        {
            auto interop = winrt::get_activation_factory<
                wgc::GraphicsCaptureItem, ::IGraphicsCaptureItemInterop>();
            hr = interop->CreateForWindow(
                opt.hwnd, winrt::guid_of<wgc::GraphicsCaptureItem>(),
                winrt::put_abi(item));
            if (FAILED(hr) || !item) {
                LogLine("[wincap] CreateForWindow failed hr=0x%08lX",
                        static_cast<unsigned long>(hr));
                ::timeEndPeriod(1);
                return EXIT_BAD_WINDOW;
            }
        }

        // --- 出力寸法を確定。以後この値は絶対に変えない ---
        auto itemSize = item.Size();
        g_outW = itemSize.Width  & ~1;   // 偶数へ切り下げ（奇数だと下流が嫌がる）
        g_outH = itemSize.Height & ~1;
        if (g_outW < 16 || g_outH < 16) {
            LogLine("[wincap] window is too small: %dx%d", itemSize.Width, itemSize.Height);
            ::timeEndPeriod(1);
            return EXIT_BAD_WINDOW;
        }
        const size_t frameBytes = static_cast<size_t>(g_outW) * g_outH * 4;
        g_latest.assign(frameBytes, 0);
        for (size_t i = 3; i < frameBytes; i += 4) {
            g_latest[i] = 255;   // 初期状態は「不透明な黒」
        }

        LogLine("[wincap] start hwnd=%llu fps=%d draw_mouse=%d sink=%s",
                static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(opt.hwnd)),
                opt.fps, opt.drawMouse ? 1 : 0,
                opt.pipeName.empty() ? "file" : "pipe");

        // --- 出力先を用意 ---
        if (!opt.pipeName.empty()) {
            if (!sink.CreatePipe(opt.pipeName)) {
                ::timeEndPeriod(1);
                return EXIT_SINK_FAILED;
            }
        } else {
            if (!sink.CreateOutFile(opt.outFile)) {
                ::timeEndPeriod(1);
                return EXIT_SINK_FAILED;
            }
        }

        // ★ハンドシェイク。Python 側はこの一行を待ってから ffmpeg を起こす。
        //   パイプを作った後・接続を待つ前に出すこと。順序を逆にすると、
        //   ffmpeg が存在しないパイプを開きに行って落ちる。
        LogLine("[wincap] ready size=%dx%d format=bgra", g_outW, g_outH);

        if (!opt.pipeName.empty()) {
            if (!sink.WaitForClient(opt.connectTimeoutSec)) {
                ::timeEndPeriod(1);
                return EXIT_SINK_FAILED;
            }
        }

        // --- キャプチャ開始 ---
        const auto pixelFormat = wgdx::DirectXPixelFormat::B8G8R8A8UIntNormalized;
        framePool = wgc::Direct3D11CaptureFramePool::CreateFreeThreaded(
            winrtDevice, pixelFormat, 2, itemSize);

        item.Closed([](wgc::GraphicsCaptureItem const&,
                       winrt::Windows::Foundation::IInspectable const&) {
            LogLine("[wincap] capture item closed");
            RequestStop(EXIT_BAD_WINDOW, "item-closed");
        });

        framePool.FrameArrived(
            [pixelFormat, winrtDevice](wgc::Direct3D11CaptureFramePool const& sender,
                                       winrt::Windows::Foundation::IInspectable const&) {
            // ★ここから例外を外へ投げないこと。WinRT のコールバックから
            //   投げるとプロセスごと落ちる。
            try {
                auto frame = sender.TryGetNextFrame();
                if (!frame) {
                    return;
                }
                auto contentSize = frame.ContentSize();
                auto texture = GetTextureFromSurface(frame.Surface());

                D3D11_TEXTURE2D_DESC td{};
                texture->GetDesc(&td);
                int srcW = static_cast<int>(td.Width);
                int srcH = static_cast<int>(td.Height);
                // 有効領域は ContentSize。プールのバッファはそれより大きいことがある。
                if (contentSize.Width  > 0 && contentSize.Width  < srcW) srcW = contentSize.Width;
                if (contentSize.Height > 0 && contentSize.Height < srcH) srcH = contentSize.Height;

                if (EnsureStaging(static_cast<int>(td.Width),
                                  static_cast<int>(td.Height), td.Format)) {
                    g_d3dContext->CopyResource(g_staging.get(), texture.get());
                    D3D11_MAPPED_SUBRESOURCE mapped{};
                    HRESULT mhr = g_d3dContext->Map(g_staging.get(), 0,
                                                    D3D11_MAP_READ, 0, &mapped);
                    if (SUCCEEDED(mhr)) {
                        {
                            std::lock_guard<std::mutex> lock(g_frameMutex);
                            // ★RowPitch == width*4 を仮定してはいけない（実機で
                            //   パディングが入る）。行ごとに写す。
                            BlitCenter(static_cast<const uint8_t*>(mapped.pData),
                                       static_cast<int>(mapped.RowPitch),
                                       srcW, srcH, g_latest, g_outW, g_outH);
                        }
                        g_latestSeq.fetch_add(1);
                        g_d3dContext->Unmap(g_staging.get(), 0);
                    }
                }

                // ウィンドウがリサイズされたらプールだけ作り直す。
                // 出力寸法（g_outW/g_outH）は動かさない。
                if (contentSize.Width  != static_cast<int32_t>(td.Width) ||
                    contentSize.Height != static_cast<int32_t>(td.Height)) {
                    if (contentSize.Width > 0 && contentSize.Height > 0) {
                        sender.Recreate(winrtDevice, pixelFormat, 2, contentSize);
                        g_statResize.fetch_add(1);
                    }
                }
            } catch (winrt::hresult_error const& e) {
                LogLine("[wincap] FrameArrived error hr=0x%08lX",
                        static_cast<unsigned long>(e.code()));
            } catch (...) {
                LogLine("[wincap] FrameArrived unknown error");
            }
        });

        session = framePool.CreateCaptureSession(item);
        try {
            session.IsCursorCaptureEnabled(opt.drawMouse);
        } catch (...) {
            LogLine("[wincap] IsCursorCaptureEnabled is unavailable -> continuing");
        }
        if (opt.noBorder) {
            // 古い OS には無い。失敗しても枠が出るだけで機能は成立するので握る。
            try {
                using namespace winrt::Windows::Security::Authorization::AppCapabilityAccess;
                auto status = wgc::GraphicsCaptureAccess::RequestAccessAsync(
                    wgc::GraphicsCaptureAccessKind::Borderless).get();
                if (status != AppCapabilityAccessStatus::Allowed) {
                    LogLine("[wincap] borderless access was not granted -> border may show");
                }
                session.IsBorderRequired(false);
            } catch (...) {
                LogLine("[wincap] IsBorderRequired is unavailable -> border may show");
            }
        }
        session.StartCapture();

        if (opt.parentPid) {
            watchdog = std::thread(ParentWatchdog, opt.parentPid);
        }

        // --- ライタースレッド：壁時計で fps 通りに書き出す ---
        // ★WGC は変化があったときだけフレームを配る。到着に同期させると
        //   静止画面で入力が途切れて下流が壊れる。新しい絵が無ければ
        //   直前のフレームをもう一度送る。
        writer = std::thread([&sink, &opt, frameBytes]() {
            std::vector<uint8_t> out(frameBytes, 0);
            uint64_t lastSeq = 0;
            uint64_t sinceStats = 0;
            const auto period = std::chrono::nanoseconds(1000000000LL / opt.fps);
            const auto started = std::chrono::steady_clock::now();
            auto next = started;
            auto lastStats = started;
            uint64_t lastSentAtStats = 0;

            while (!g_stop.load()) {
                next += period;
                std::this_thread::sleep_until(next);
                if (g_stop.load()) break;

                uint64_t seq;
                {
                    // ★ロックを持ったまま WriteFile しない。1フレーム約8MBを
                    //   書いている間 FrameArrived が止まり、取り込みが詰まる。
                    std::lock_guard<std::mutex> lock(g_frameMutex);
                    memcpy(out.data(), g_latest.data(), frameBytes);
                    seq = g_latestSeq.load();
                }
                if (seq == lastSeq) {
                    g_statDup.fetch_add(1);
                } else {
                    lastSeq = seq;
                }

                if (!sink.WriteAll(out.data(), frameBytes)) {
                    // 読み手が消えただけ。異常ではない。
                    LogLine("[wincap] sink closed by reader");
                    RequestStop(EXIT_OK, "reader-gone");
                    break;
                }
                g_statSent.fetch_add(1);
                ++sinceStats;

                const auto now = std::chrono::steady_clock::now();
                if (opt.durationSec > 0 &&
                    now - started >= std::chrono::seconds(opt.durationSec)) {
                    RequestStop(EXIT_OK, "duration");
                    break;
                }
                if (opt.statsSec > 0 &&
                    now - lastStats >= std::chrono::seconds(opt.statsSec)) {
                    const double elapsed =
                        std::chrono::duration<double>(now - lastStats).count();
                    const uint64_t sent = g_statSent.load();
                    LogLine("[wincap] stats sent=%llu fps=%.1f dup=%llu resize=%llu",
                            static_cast<unsigned long long>(sent),
                            elapsed > 0 ? (sent - lastSentAtStats) / elapsed : 0.0,
                            static_cast<unsigned long long>(g_statDup.load()),
                            static_cast<unsigned long long>(g_statResize.load()));
                    lastStats = now;
                    lastSentAtStats = sent;
                    sinceStats = 0;
                }
                (void)sinceStats;

                // 遅れが溜まったら追いつくのを諦めて刻み直す（雪だるまを防ぐ）
                if (now - next > std::chrono::milliseconds(500)) {
                    next = now;
                }
            }
        });

        // 停止まで待つ
        while (!g_stop.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    } catch (winrt::hresult_error const& e) {
        LogLine("[wincap] fatal hr=0x%08lX", static_cast<unsigned long>(e.code()));
        RequestStop(EXIT_NO_WGC, "fatal-hresult");
    } catch (std::exception const& e) {
        LogLine("[wincap] fatal: %s", e.what());
        RequestStop(EXIT_NO_WGC, "fatal-exception");
    }

    // --- 後始末。順序を守ること ---
    g_stop.store(true);
    try { if (session) session.Close(); } catch (...) {}
    try { if (framePool) framePool.Close(); } catch (...) {}
    if (writer.joinable())   writer.join();
    if (watchdog.joinable()) watchdog.join();
    sink.Close();
    g_staging = nullptr;
    g_d3dContext = nullptr;
    g_d3dDevice = nullptr;
    ::timeEndPeriod(1);

    rc = g_exitCode.load();
    LogLine("[wincap] exit code=%d reason=%s sent=%llu dup=%llu resize=%llu",
            rc, g_exitReason,
            static_cast<unsigned long long>(g_statSent.load()),
            static_cast<unsigned long long>(g_statDup.load()),
            static_cast<unsigned long long>(g_statResize.load()));
    return rc;
}
