#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <stdio.h>
#include "resource.h"

#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "shlwapi.lib")

#define REGKEY_UNINSTALL \
    L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinZapp"

/* ── Read install directory from registry ─────────────────────────────── */

static BOOL get_install_dir(wchar_t *out, DWORD size)
{
    HKEY hkey;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, REGKEY_UNINSTALL, 0,
                      KEY_READ, &hkey) != ERROR_SUCCESS)
        return FALSE;
    DWORD type = REG_SZ;
    LONG r = RegQueryValueExW(hkey, L"InstallLocation", NULL, &type,
                              (BYTE *)out, &size);
    RegCloseKey(hkey);
    return r == ERROR_SUCCESS;
}

/* ── Delete files listed in installed_files.dat ──────────────────────── */

static void delete_installed_files(const wchar_t *install_dir)
{
    wchar_t list_path[MAX_PATH];
    swprintf(list_path, MAX_PATH, L"%s\\installed_files.dat", install_dir);

    FILE *f = _wfopen(list_path, L"r, ccs=UTF-8");
    if (!f) return;

    wchar_t line[MAX_PATH];
    while (fgetws(line, MAX_PATH, f)) {
        /* Strip newline */
        size_t len = wcslen(line);
        while (len > 0 && (line[len - 1] == L'\n' || line[len - 1] == L'\r'))
            line[--len] = L'\0';
        if (len == 0) continue;
        SetFileAttributesW(line, FILE_ATTRIBUTE_NORMAL);
        DeleteFileW(line);
    }
    fclose(f);

    /* Delete the list file itself */
    SetFileAttributesW(list_path, FILE_ATTRIBUTE_NORMAL);
    DeleteFileW(list_path);
}

/* ── Remove shortcuts ─────────────────────────────────────────────────── */

static void remove_shortcuts(void)
{
    wchar_t path[MAX_PATH];

    /* Desktop */
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, path))) {
        wchar_t link[MAX_PATH];
        swprintf(link, MAX_PATH, L"%s\\WinZapp.lnk", path);
        DeleteFileW(link);
    }

    /* Start Menu (common programs) */
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_COMMON_PROGRAMS, NULL, 0, path))) {
        wchar_t link[MAX_PATH];
        swprintf(link, MAX_PATH, L"%s\\WinZapp.lnk", path);
        DeleteFileW(link);
    }
}

/* ── Remove registry entry ────────────────────────────────────────────── */

static void remove_registry_entry(void)
{
    RegDeleteKeyW(HKEY_LOCAL_MACHINE, REGKEY_UNINSTALL);
}

/* ── Schedule self-delete via temp batch file ─────────────────────────── */

static void schedule_self_delete(const wchar_t *uninstall_exe,
                                  const wchar_t *install_dir)
{
    wchar_t temp[MAX_PATH];
    GetTempPathW(MAX_PATH, temp);
    wchar_t bat_path[MAX_PATH];
    swprintf(bat_path, MAX_PATH, L"%swzuninstall.bat", temp);

    FILE *f = _wfopen(bat_path, L"w");
    if (!f) return;

    /* Write batch script */
    fprintf(f, "@echo off\r\n");
    fprintf(f, "ping -n 2 127.0.0.1 >nul\r\n");
    fprintf(f, ":loop\r\n");
    fprintf(f, "del /f /q \"%ws\"\r\n", uninstall_exe);
    fprintf(f, "if exist \"%ws\" goto loop\r\n", uninstall_exe);
    fprintf(f, "rmdir /s /q \"%ws\"\r\n", install_dir);
    fprintf(f, "del \"%%~f0\"\r\n");
    fclose(f);

    ShellExecuteW(NULL, L"open", bat_path, NULL, NULL, SW_HIDE);
}

/* ── Dialog procedure ─────────────────────────────────────────────────── */

static wchar_t g_install_dir[MAX_PATH];
static wchar_t g_uninstall_exe[MAX_PATH];

static INT_PTR CALLBACK DlgProc(HWND hDlg, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg) {
    case WM_INITDIALOG:
        if (!get_install_dir(g_install_dir, MAX_PATH * sizeof(wchar_t))) {
            MessageBoxW(hDlg,
                L"Não foi possível encontrar o diretório de instalação do WinZapp.\n"
                L"O programa pode já ter sido desinstalado.",
                L"WinZapp", MB_OK | MB_ICONWARNING);
            EndDialog(hDlg, IDABORT);
        }
        swprintf(g_uninstall_exe, MAX_PATH, L"%s\\uninstall.exe", g_install_dir);
        return TRUE;

    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDC_INSTALL: {  /* "Desinstalar" button */
            EnableWindow(GetDlgItem(hDlg, IDC_INSTALL), FALSE);
            EnableWindow(GetDlgItem(hDlg, IDC_CANCEL),  FALSE);

            delete_installed_files(g_install_dir);
            remove_shortcuts();
            remove_registry_entry();
            schedule_self_delete(g_uninstall_exe, g_install_dir);

            MessageBoxW(hDlg,
                L"WinZapp foi desinstalado com sucesso.",
                L"Desinstalação concluída", MB_OK | MB_ICONINFORMATION);
            EndDialog(hDlg, IDOK);
            return TRUE;
        }
        case IDC_CANCEL:
            EndDialog(hDlg, IDCANCEL);
            return TRUE;
        }
        break;

    case WM_CLOSE:
        EndDialog(hDlg, IDCANCEL);
        return TRUE;
    }
    return FALSE;
}

/* ── Entry point ──────────────────────────────────────────────────────── */

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrev,
                   LPSTR lpCmdLine, int nCmdShow)
{
    (void)hPrev; (void)lpCmdLine; (void)nCmdShow;

    INITCOMMONCONTROLSEX icc = { sizeof(icc), ICC_STANDARD_CLASSES };
    InitCommonControlsEx(&icc);

    DialogBoxW(hInstance, MAKEINTRESOURCEW(IDD_UNINSTALL), NULL, DlgProc);
    return 0;
}
