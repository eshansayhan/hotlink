#pragma once
#include <windows.h>
#include <string>

class RegistryUtils {
public:
    static const char* GetSubKey() {
        return "Software\\HFVideoPlatform";
    }

    // Regedit'e String Yaz
    static bool WriteAppSetting(const std::string& keyName, const std::string& data) {
        HKEY hKey;
        if (RegCreateKeyExA(HKEY_CURRENT_USER, GetSubKey(), 0, NULL, REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            RegSetValueExA(hKey, keyName.c_str(), 0, REG_SZ, (const BYTE*)data.c_str(), (DWORD)(data.length() + 1));
            RegCloseKey(hKey);
            return true;
        }
        return false;
    }

    // Regedit'ten String Oku
    static std::string ReadAppSetting(const std::string& keyName, const std::string& defaultValue = "") {
        HKEY hKey;
        std::string result = defaultValue;
        if (RegOpenKeyExA(HKEY_CURRENT_USER, GetSubKey(), 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            char buffer[1024];
            DWORD bufferSize = sizeof(buffer);
            if (RegQueryValueExA(hKey, keyName.c_str(), NULL, NULL, (LPBYTE)buffer, &bufferSize) == ERROR_SUCCESS) {
                result = buffer;
            }
            RegCloseKey(hKey);
        }
        return result;
    }

    // Regedit'e DWORD (Sayi / Bayrak) Yaz
    static bool WriteDword(const std::string& keyName, DWORD val) {
        HKEY hKey;
        if (RegCreateKeyExA(HKEY_CURRENT_USER, GetSubKey(), 0, NULL, REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            RegSetValueExA(hKey, keyName.c_str(), 0, REG_DWORD, (const BYTE*)&val, sizeof(DWORD));
            RegCloseKey(hKey);
            return true;
        }
        return false;
    }

    // Regedit'ten DWORD Oku
    static DWORD ReadDword(const std::string& keyName, DWORD defaultValue = 0) {
        HKEY hKey;
        DWORD result = defaultValue;
        if (RegOpenKeyExA(HKEY_CURRENT_USER, GetSubKey(), 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            DWORD val = 0;
            DWORD valSize = sizeof(DWORD);
            if (RegQueryValueExA(hKey, keyName.c_str(), NULL, NULL, (LPBYTE)&val, &valSize) == ERROR_SUCCESS) {
                result = val;
            }
            RegCloseKey(hKey);
        }
        return result;
    }

    // Regedit'ten Boolean Oku
    static bool ReadBool(const std::string& keyName, bool defaultValue = false) {
        return ReadDword(keyName, defaultValue ? 1 : 0) != 0;
    }

    // Regedit'e Boolean Yaz
    static bool WriteBool(const std::string& keyName, bool val) {
        return WriteDword(keyName, val ? 1 : 0);
    }

    // Windows Baslangicinda Calistirma (Run on Startup)
    static bool SetAutoStart(bool enable, const std::string& exePath) {
        HKEY hKey;
        const char* runSubKey = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
        if (RegOpenKeyExA(HKEY_CURRENT_USER, runSubKey, 0, KEY_WRITE, &hKey) == ERROR_SUCCESS) {
            if (enable) {
                std::string cmd = "\"" + exePath + "\" --tray";
                RegSetValueExA(hKey, "HFVideoPlatform", 0, REG_SZ, (const BYTE*)cmd.c_str(), (DWORD)(cmd.length() + 1));
            } else {
                RegDeleteValueA(hKey, "HFVideoPlatform");
            }
            RegCloseKey(hKey);
            WriteBool("AutoStart", enable);
            return true;
        }
        return false;
    }

    static bool IsAutoStartEnabled() {
        HKEY hKey;
        const char* runSubKey = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
        bool enabled = false;
        if (RegOpenKeyExA(HKEY_CURRENT_USER, runSubKey, 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            if (RegQueryValueExA(hKey, "HFVideoPlatform", NULL, NULL, NULL, NULL) == ERROR_SUCCESS) {
                enabled = true;
            }
            RegCloseKey(hKey);
        }
        return enabled;
    }
};
