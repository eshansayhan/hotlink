#pragma once
#include <windows.h>
#include <shellapi.h>
#include <string>
#include <functional>
#include <thread>
#include <atomic>
#include "RegistryUtils.h"

#define WM_TRAYICON (WM_USER + 101)
#define ID_TRAY_ICON 9001

#define IDM_OPEN_WEB       2001
#define IDM_STATUS         2002
#define IDM_TOGGLE_CONSOLE 2003
#define IDM_OPEN_PACK      2004
#define IDM_SETTINGS       2005
#define IDM_EXIT           2006

class TrayManager {
private:
    HWND m_hWnd = NULL;
    NOTIFYICONDATAA m_nid = {};
    HWND m_hConsole = NULL;
    bool m_consoleVisible = true;
    std::atomic<bool> m_running{false};
    std::function<void()> m_onExitCallback;
    std::thread m_msgLoopThread;

    static LRESULT CALLBACK WindowProc(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
        TrayManager* self = (TrayManager*)GetWindowLongPtrA(hWnd, GWLP_USERDATA);
        if (!self) return DefWindowProcA(hWnd, uMsg, wParam, lParam);

        if (uMsg == WM_TRAYICON) {
            if (lParam == WM_RBUTTONUP || lParam == WM_CONTEXTMENU) {
                self->ShowContextMenu();
            } else if (lParam == WM_LBUTTONDBLCLK) {
                ShellExecuteA(NULL, "open", "http://127.0.0.1:8080", NULL, NULL, SW_SHOWNORMAL);
            }
            return 0;
        }

        if (uMsg == WM_COMMAND) {
            int wmId = LOWORD(wParam);
            switch (wmId) {
                case IDM_OPEN_WEB:
                    ShellExecuteA(NULL, "open", "http://127.0.0.1:8080", NULL, NULL, SW_SHOWNORMAL);
                    break;
                case IDM_TOGGLE_CONSOLE:
                    self->ToggleConsole();
                    break;
                case IDM_OPEN_PACK: {
                    char path[MAX_PATH];
                    GetModuleFileNameA(NULL, path, MAX_PATH);
                    std::string exeDir(path);
                    size_t p = exeDir.find_last_of("\\/");
                    std::string packExe = ((p != std::string::npos) ? exeDir.substr(0, p) : ".") + "\\PackManager.exe";
                    ShellExecuteA(NULL, "open", packExe.c_str(), NULL, NULL, SW_SHOWNORMAL);
                    break;
                }
                case IDM_SETTINGS:
                    ShellExecuteA(NULL, "open", "regedit.exe", NULL, NULL, SW_SHOWNORMAL);
                    break;
                case IDM_EXIT:
                    if (self->m_onExitCallback) {
                        self->m_onExitCallback();
                    }
                    PostQuitMessage(0);
                    break;
            }
            return 0;
        }

        return DefWindowProcA(hWnd, uMsg, wParam, lParam);
    }

public:
    TrayManager() {
        m_hConsole = GetConsoleWindow();
    }

    ~TrayManager() {
        Stop();
    }

    void SetExitCallback(std::function<void()> cb) {
        m_onExitCallback = cb;
    }

    bool Start(bool startHidden = false) {
        if (m_running) return true;
        m_running = true;

        m_msgLoopThread = std::thread([this, startHidden]() {
            HINSTANCE hInstance = GetModuleHandle(NULL);
            WNDCLASSA wc = {};
            wc.lpfnWndProc = WindowProc;
            wc.hInstance = hInstance;
            wc.lpszClassName = "HFVideoPlatform_TrayClass";
            RegisterClassA(&wc);

            m_hWnd = CreateWindowExA(0, wc.lpszClassName, "HFVideoPlatform_Tray", 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, hInstance, NULL);
            SetWindowLongPtrA(m_hWnd, GWLP_USERDATA, (LONG_PTR)this);

            // Icon'u yukle (Resource IDI_APP_ICON veya varsayilan logo)
            HICON hIcon = (HICON)LoadImageA(hInstance, MAKEINTRESOURCEA(1), IMAGE_ICON, 16, 16, LR_DEFAULTCOLOR);
            if (!hIcon) {
                hIcon = LoadIconA(NULL, IDI_APPLICATION);
            }

            ZeroMemory(&m_nid, sizeof(m_nid));
            m_nid.cbSize = sizeof(NOTIFYICONDATAA);
            m_nid.hWnd = m_hWnd;
            m_nid.uID = ID_TRAY_ICON;
            m_nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP | NIF_INFO;
            m_nid.uCallbackMessage = WM_TRAYICON;
            m_nid.hIcon = hIcon;
            strcpy_s(m_nid.szTip, "HFVideoPlatform Yerel Video Motoru (Aktif)");

            // Bildirim Balonu (Windows Tray Balloon)
            strcpy_s(m_nid.szInfoTitle, "HFVideoPlatform Aktif!");
            strcpy_s(m_nid.szInfo, "Yerel video motoru sistem tepsisinde çalışıyor.");
            m_nid.dwInfoFlags = NIIF_INFO;

            Shell_NotifyIconA(NIM_ADD, &m_nid);

            if (startHidden && m_hConsole) {
                ShowWindow(m_hConsole, SW_HIDE);
                m_consoleVisible = false;
            }

            MSG msg;
            while (GetMessageA(&msg, NULL, 0, 0) > 0) {
                TranslateMessage(&msg);
                DispatchMessageA(&msg);
            }

            Shell_NotifyIconA(NIM_DELETE, &m_nid);
        });

        return true;
    }

    void Stop() {
        if (!m_running) return;
        m_running = false;
        if (m_hWnd) {
            PostMessageA(m_hWnd, WM_CLOSE, 0, 0);
        }
        if (m_msgLoopThread.joinable()) {
            m_msgLoopThread.detach();
        }
    }

    void ToggleConsole() {
        if (!m_hConsole) return;
        m_consoleVisible = !m_consoleVisible;
        ShowWindow(m_hConsole, m_consoleVisible ? SW_SHOW : SW_HIDE);
        if (m_consoleVisible) {
            SetForegroundWindow(m_hConsole);
        }
    }

    void ShowContextMenu() {
        POINT pt;
        GetCursorPos(&pt);
        HMENU hMenu = CreatePopupMenu();

        AppendMenuA(hMenu, MF_STRING, IDM_OPEN_WEB, "🌐 Web Paneli Ac (127.0.0.1:8080)");
        SetMenuDefaultItem(hMenu, IDM_OPEN_WEB, FALSE); // Kalın yazı

        AppendMenuA(hMenu, MF_STRING | MF_GRAYED, IDM_STATUS, "Video Motoru: Aktif (8080)");
        AppendMenuA(hMenu, MF_SEPARATOR, 0, NULL);

        std::string toggleTxt = m_consoleVisible ? "🖥️ Konsol Penceresini Gizle" : "🖥️ Konsol Penceresini Goster";
        AppendMenuA(hMenu, MF_STRING, IDM_TOGGLE_CONSOLE, toggleTxt.c_str());
        AppendMenuA(hMenu, MF_STRING, IDM_OPEN_PACK, "📦 PackManager (Paket Yoneticisi)");
        AppendMenuA(hMenu, MF_STRING, IDM_SETTINGS, "⚙️ Regedit Ayarlari");

        AppendMenuA(hMenu, MF_SEPARATOR, 0, NULL);
        AppendMenuA(hMenu, MF_STRING, IDM_EXIT, "❌ HFVideoPlatform'u Tamamen Kapat");

        SetForegroundWindow(m_hWnd);
        TrackPopupMenu(hMenu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.x, pt.y, 0, m_hWnd, NULL);
        DestroyMenu(hMenu);
    }
};
