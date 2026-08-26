#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <stdint.h>
#include <stdio.h>
#include "resource.h"

#define REGKEY_UNINSTALL \
    L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinZapp"

/* ── Read install directory from registry ─────────────────────────────── */

static BOOL get_install_dir(wchar_t *out, DWORD char_count)
{
    /* The installer registers under HKEY_LOCAL_MACHINE when it can (running
     * elevated) and falls back to HKEY_CURRENT_USER otherwise (the default,
     * non-admin install path) — check both, machine-wide first, so this
     * finds the entry regardless of which one the install actually used. */
    const HKEY hives[] = { HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER };
    for (int i = 0; i < 2; i++) {
        HKEY hkey;
        if (RegOpenKeyExW(hives[i], REGKEY_UNINSTALL, 0,
                          KEY_READ, &hkey) != ERROR_SUCCESS)
            continue;
        DWORD type  = REG_SZ;
        DWORD bytes = char_count * sizeof(wchar_t);
        LONG  r = RegQueryValueExW(hkey, L"InstallLocation", NULL, &type,
                                   (BYTE *)out, &bytes);
        RegCloseKey(hkey);
        if (r == ERROR_SUCCESS)
            return TRUE;
    }
    return FALSE;
}

/* Build an extended-length (\\?\) form of an absolute path so DeleteFileW is
 * not limited to MAX_PATH — mirrors installer.c's to_extended_path(), needed
 * because the installer can lay down files deeper than 260 chars under a
 * long install path (deep node_modules/ trees). */
static void to_extended_path(wchar_t *out, size_t out_cap, const wchar_t *in)
{
    if (in[0] == L'\\' && in[1] == L'\\' && in[2] == L'?' && in[3] == L'\\') {
        wcsncpy(out, in, out_cap - 1);
        out[out_cap - 1] = L'\0';
        return;
    }
    if (((in[0] >= L'A' && in[0] <= L'Z') || (in[0] >= L'a' && in[0] <= L'z')) && in[1] == L':') {
        swprintf(out, (int)out_cap, L"\\\\?\\%s", in);
    } else {
        wcsncpy(out, in, out_cap - 1);
        out[out_cap - 1] = L'\0';
    }
}

/* ── Delete files listed in installed_files.dat ──────────────────────── */

static void delete_installed_files(const wchar_t *install_dir)
{
    wchar_t list_path[MAX_PATH];
    swprintf(list_path, MAX_PATH, L"%s\\installed_files.dat", install_dir);

    /* Read the whole file into memory as raw bytes, then interpret as UTF-16LE */
    HANDLE hf = CreateFileW(list_path, GENERIC_READ, FILE_SHARE_READ,
                            NULL, OPEN_EXISTING, 0, NULL);
    if (hf == INVALID_HANDLE_VALUE) return;

    LARGE_INTEGER fsize_li;
    GetFileSizeEx(hf, &fsize_li);
    DWORD fsize = (DWORD)fsize_li.QuadPart;

    BYTE *raw = (BYTE *)malloc(fsize + 4);   /* +4 for null terminator */
    if (!raw) { CloseHandle(hf); return; }

    DWORD read_bytes = 0;
    ReadFile(hf, raw, fsize, &read_bytes, NULL);
    CloseHandle(hf);
    raw[read_bytes]     = 0;
    raw[read_bytes + 1] = 0;
    raw[read_bytes + 2] = 0;
    raw[read_bytes + 3] = 0;

    wchar_t *wbuf = (wchar_t *)raw;
    /* Skip UTF-16LE BOM if present */
    if (*wbuf == 0xFEFF) wbuf++;

    /* Parse one path per line */
    wchar_t *p = wbuf;
    while (*p) {
        wchar_t *end = wcspbrk(p, L"\r\n");
        if (!end) end = p + wcslen(p);
        wchar_t save = *end;
        *end = L'\0';
        if (wcslen(p) > 0) {
            wchar_t p_ext[32768];
            to_extended_path(p_ext, 32768, p);
            SetFileAttributesW(p_ext, FILE_ATTRIBUTE_NORMAL);
            DeleteFileW(p_ext);
        }
        *end = save;
        while (*end == L'\r' || *end == L'\n') end++;
        p = end;
    }
    free(raw);

    /* Delete the list file itself */
    SetFileAttributesW(list_path, FILE_ATTRIBUTE_NORMAL);
    DeleteFileW(list_path);
}

/* ── Remove shortcuts ─────────────────────────────────────────────────── */

static void remove_shortcuts(void)
{
    wchar_t path[MAX_PATH];

    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, path))) {
        wchar_t link[MAX_PATH];
        swprintf(link, MAX_PATH, L"%s\\WinZapp.lnk", path);
        DeleteFileW(link);
    }

    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_COMMON_PROGRAMS, NULL, 0, path))) {
        wchar_t link[MAX_PATH];
        swprintf(link, MAX_PATH, L"%s\\WinZapp.lnk", path);
        DeleteFileW(link);
    }
}

/* ── Remove registry entry ────────────────────────────────────────────── */

static void remove_registry_entry(void)
{
    /* Remove from both hives — harmless no-op on whichever one the install
     * didn't use (see get_install_dir()). */
    RegDeleteKeyW(HKEY_LOCAL_MACHINE, REGKEY_UNINSTALL);
    RegDeleteKeyW(HKEY_CURRENT_USER, REGKEY_UNINSTALL);
}

/* ── Schedule self-delete via temp batch file ─────────────────────────── */

static void schedule_self_delete(const wchar_t *uninstall_exe,
                                  const wchar_t *install_dir)
{
    wchar_t temp_dir[MAX_PATH];
    GetTempPathW(MAX_PATH, temp_dir);
    wchar_t bat_path[MAX_PATH];
    swprintf(bat_path, MAX_PATH, L"%swzuninstall.bat", temp_dir);

    /* Convert paths to the OEM code page, not ANSI: cmd.exe reads a .bat
     * file back in the OEM code page (CP852 on a Polish Windows, CP850 on
     * a Portuguese one, ...), which is not the same as CP_ACP for any
     * non-ASCII character. Writing ANSI bytes here and having cmd decode
     * them as OEM is exactly what turned a path like
     * "C:\Users\Paweł\AppData\Local\WinZapp" into mojibake that does not
     * exist on disk — updater.py hit the identical mismatch on the
     * self-update path (see its _oem_encoding(), issue #83) and this side
     * never got the matching fix. del/rmdir below then silently target a
     * path that was never there: the :loop wait can spin forever waiting
     * for a uninstall_a delete that already "succeeded" against the wrong
     * name, and even when it doesn't, the success dialog still fires while
     * every file and the install folder itself are left behind. */
    char uninstall_a[MAX_PATH], install_a[MAX_PATH], bat_a[MAX_PATH];
    int ok = WideCharToMultiByte(CP_OEMCP, 0, uninstall_exe, -1, uninstall_a, MAX_PATH, NULL, NULL)
          && WideCharToMultiByte(CP_OEMCP, 0, install_dir,   -1, install_a,   MAX_PATH, NULL, NULL)
          && WideCharToMultiByte(CP_OEMCP, 0, bat_path,      -1, bat_a,       MAX_PATH, NULL, NULL);
    if (!ok) return;   /* a character with no OEM representation at all —
                         * nothing safe to write, same as a failed conversion
                         * on the updater.py side. */

    FILE *f = fopen(bat_a, "w");
    if (!f) return;

    fprintf(f, "@echo off\r\n");
    fprintf(f, "ping -n 2 127.0.0.1 >nul\r\n");
    fprintf(f, ":loop\r\n");
    fprintf(f, "del /f /q \"%s\"\r\n",          uninstall_a);
    fprintf(f, "if exist \"%s\" goto loop\r\n", uninstall_a);
    fprintf(f, "rmdir /s /q \"%s\"\r\n",        install_a);
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
        if (!get_install_dir(g_install_dir, MAX_PATH)) {
            MessageBoxW(hDlg,
                L"Não foi possível encontrar o diretório de instalação do WinZapp.\n"
                L"O programa pode já ter sido desinstalado.",
                L"WinZapp", MB_OK | MB_ICONWARNING);
            EndDialog(hDlg, IDABORT);
            return TRUE;
        }
        swprintf(g_uninstall_exe, MAX_PATH, L"%s\\uninstall.exe", g_install_dir);
        return TRUE;

    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDC_INSTALL: {
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
