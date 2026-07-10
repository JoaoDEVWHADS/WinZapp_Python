#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <objbase.h>
#include <shobjidl.h>
#include <stdint.h>
#include <stdio.h>
#include "resource.h"

#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "shlwapi.lib")

/* ── ZIP structures (no compression — ZIP_STORED only) ───────────────── */

#define ZIP_LOCAL_SIG  0x04034b50UL
#define ZIP_CD_SIG     0x02014b50UL
#define ZIP_EOCD_SIG   0x06054b50UL

#pragma pack(push, 1)
typedef struct {
    uint32_t sig;
    uint16_t ver_needed;
    uint16_t flags;
    uint16_t compression;
    uint16_t mod_time;
    uint16_t mod_date;
    uint32_t crc32;
    uint32_t comp_size;
    uint32_t uncomp_size;
    uint16_t fname_len;
    uint16_t extra_len;
} ZipLocal;

typedef struct {
    uint32_t sig;
    uint16_t ver_made;
    uint16_t ver_needed;
    uint16_t flags;
    uint16_t compression;
    uint16_t mod_time;
    uint16_t mod_date;
    uint32_t crc32;
    uint32_t comp_size;
    uint32_t uncomp_size;
    uint16_t fname_len;
    uint16_t extra_len;
    uint16_t comment_len;
    uint16_t disk_start;
    uint16_t int_attr;
    uint32_t ext_attr;
    uint32_t local_off;
} ZipCentral;

typedef struct {
    uint32_t sig;
    uint16_t disk_num;
    uint16_t cd_disk;
    uint16_t cd_entries_disk;
    uint16_t cd_entries_total;
    uint32_t cd_size;
    uint32_t cd_off;
    uint16_t comment_len;
} ZipEOCD;
#pragma pack(pop)

/* ── Custom window messages ───────────────────────────────────────────── */

#define WM_INSTALL_PROGRESS  (WM_USER + 1)   /* wParam=done, lParam=total */
#define WM_INSTALL_DONE      (WM_USER + 2)
#define WM_INSTALL_ERROR     (WM_USER + 3)   /* lParam=error string (heap) */

/* ── Globals ──────────────────────────────────────────────────────────── */

static HWND  g_hDlg      = NULL;
static BOOL  g_cancelled = FALSE;

typedef struct {
    wchar_t  install_dir[MAX_PATH];
    BOOL     desktop_sc;
    BOOL     startmenu_sc;
} InstallParams;

/* ── ZIP helpers ──────────────────────────────────────────────────────── */

static BOOL read_at(HANDLE hf, uint64_t offset, void *buf, DWORD len)
{
    LARGE_INTEGER li;
    li.QuadPart = (LONGLONG)offset;
    if (!SetFilePointerEx(hf, li, NULL, FILE_BEGIN)) return FALSE;
    DWORD read = 0;
    return ReadFile(hf, buf, len, &read, NULL) && read == len;
}

static BOOL find_zip_start(HANDLE hf, uint64_t *out_zip_start)
{
    LARGE_INTEGER fs_li;
    if (!GetFileSizeEx(hf, &fs_li)) return FALSE;
    uint64_t fsize = (uint64_t)fs_li.QuadPart;

    /* Scan backwards through last 64 KB + EOCD size for the EOCD signature */
    uint64_t scan_size = 65536 + sizeof(ZipEOCD) + 65535;
    if (scan_size > fsize) scan_size = fsize;
    uint64_t scan_start = fsize - scan_size;

    uint8_t *buf = (uint8_t *)malloc((size_t)scan_size);
    if (!buf) return FALSE;

    BOOL ok = read_at(hf, scan_start, buf, (DWORD)scan_size);
    if (!ok) { free(buf); return FALSE; }

    /* Walk backwards looking for EOCD sig */
    for (int64_t i = (int64_t)(scan_size - sizeof(ZipEOCD)); i >= 0; i--) {
        uint32_t sig;
        memcpy(&sig, buf + i, 4);
        if (sig == ZIP_EOCD_SIG) {
            ZipEOCD eocd;
            memcpy(&eocd, buf + i, sizeof(ZipEOCD));
            /* zip_start = absolute position of EOCD - cd_size - cd_off */
            uint64_t eocd_abs = scan_start + (uint64_t)i;
            *out_zip_start = eocd_abs - eocd.cd_size - eocd.cd_off;
            free(buf);
            return TRUE;
        }
    }
    free(buf);
    return FALSE;
}

/* Count entries in central directory */
static int count_zip_entries(HANDLE hf, uint64_t zip_start)
{
    /* Re-find EOCD to get count */
    LARGE_INTEGER fs_li;
    if (!GetFileSizeEx(hf, &fs_li)) return 0;
    uint64_t fsize = (uint64_t)fs_li.QuadPart;
    uint64_t scan_size = 65536 + sizeof(ZipEOCD) + 65535;
    if (scan_size > fsize) scan_size = fsize;
    uint64_t scan_start = fsize - scan_size;
    uint8_t *buf = (uint8_t *)malloc((size_t)scan_size);
    if (!buf) return 0;
    if (!read_at(hf, scan_start, buf, (DWORD)scan_size)) { free(buf); return 0; }
    int count = 0;
    for (int64_t i = (int64_t)(scan_size - sizeof(ZipEOCD)); i >= 0; i--) {
        uint32_t sig; memcpy(&sig, buf + i, 4);
        if (sig == ZIP_EOCD_SIG) {
            ZipEOCD eocd; memcpy(&eocd, buf + i, sizeof(ZipEOCD));
            count = eocd.cd_entries_total;
            break;
        }
    }
    free(buf);
    return count;
}

/* Create all intermediate directories for a file path */
static void ensure_dirs(const wchar_t *path)
{
    wchar_t tmp[MAX_PATH];
    wcsncpy(tmp, path, MAX_PATH - 1);
    tmp[MAX_PATH - 1] = L'\0';
    wchar_t *p = tmp;
    if (p[1] == L':') p += 3;
    for (; *p; p++) {
        if (*p == L'\\' || *p == L'/') {
            *p = L'\0';
            CreateDirectoryW(tmp, NULL);
            *p = L'\\';
        }
    }
}

/* ── Extract all files from ZIP payload ───────────────────────────────── */

static BOOL extract_all(HWND hDlg, const wchar_t *dest_dir,
                        wchar_t ***out_files, int *out_count)
{
    wchar_t exe_path[MAX_PATH];
    GetModuleFileNameW(NULL, exe_path, MAX_PATH);

    HANDLE hf = CreateFileW(exe_path, GENERIC_READ, FILE_SHARE_READ,
                            NULL, OPEN_EXISTING, 0, NULL);
    if (hf == INVALID_HANDLE_VALUE) return FALSE;

    uint64_t zip_start = 0;
    if (!find_zip_start(hf, &zip_start)) { CloseHandle(hf); return FALSE; }

    /* Find EOCD to get cd_off and total entries */
    LARGE_INTEGER fs_li; GetFileSizeEx(hf, &fs_li);
    uint64_t fsize = (uint64_t)fs_li.QuadPart;
    uint64_t scan_size = 65536 + sizeof(ZipEOCD) + 65535;
    if (scan_size > fsize) scan_size = fsize;
    uint64_t scan_start = fsize - scan_size;
    uint8_t *scan_buf = (uint8_t *)malloc((size_t)scan_size);
    if (!scan_buf) { CloseHandle(hf); return FALSE; }
    read_at(hf, scan_start, scan_buf, (DWORD)scan_size);
    ZipEOCD eocd = {0};
    for (int64_t i = (int64_t)(scan_size - sizeof(ZipEOCD)); i >= 0; i--) {
        uint32_t sig; memcpy(&sig, scan_buf + i, 4);
        if (sig == ZIP_EOCD_SIG) { memcpy(&eocd, scan_buf + i, sizeof(ZipEOCD)); break; }
    }
    free(scan_buf);

    int total = eocd.cd_entries_total;
    uint64_t cd_pos = zip_start + eocd.cd_off;

    /* Allocate file list */
    wchar_t **files = (wchar_t **)malloc(total * sizeof(wchar_t *));
    int file_count = 0;

    /* Walk central directory */
    for (int i = 0; i < total && !g_cancelled; i++) {
        ZipCentral cd = {0};
        if (!read_at(hf, cd_pos, &cd, sizeof(ZipCentral))) break;
        if (cd.sig != ZIP_CD_SIG) break;

        /* Read filename */
        char fname_utf8[512] = {0};
        int name_len = cd.fname_len < 511 ? cd.fname_len : 511;
        read_at(hf, cd_pos + sizeof(ZipCentral), fname_utf8, name_len);
        fname_utf8[name_len] = '\0';

        cd_pos += sizeof(ZipCentral) + cd.fname_len + cd.extra_len + cd.comment_len;

        /* Skip directories */
        if (fname_utf8[name_len - 1] == '/' || fname_utf8[name_len - 1] == '\\')
            continue;

        /* Build destination path */
        wchar_t fname_w[512];
        MultiByteToWideChar(CP_UTF8, 0, fname_utf8, -1, fname_w, 512);

        /* Replace forward slashes with backslashes */
        for (wchar_t *p = fname_w; *p; p++)
            if (*p == L'/') *p = L'\\';

        wchar_t dest_path[MAX_PATH];
        swprintf(dest_path, MAX_PATH, L"%s\\%s", dest_dir, fname_w);

        /* Ensure parent directories exist */
        ensure_dirs(dest_path);

        /* Seek to local file header */
        ZipLocal local = {0};
        uint64_t local_off = zip_start + cd.local_off;
        if (!read_at(hf, local_off, &local, sizeof(ZipLocal))) continue;
        if (local.sig != ZIP_LOCAL_SIG) continue;

        uint64_t data_off = local_off + sizeof(ZipLocal) + local.fname_len + local.extra_len;

        /* Create output file */
        HANDLE hout = CreateFileW(dest_path, GENERIC_WRITE, 0, NULL,
                                  CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (hout == INVALID_HANDLE_VALUE) continue;

        /* Copy raw bytes in 64 KB chunks */
        uint32_t remaining = cd.comp_size;
        uint8_t chunk[65536];
        uint64_t read_pos = data_off;
        BOOL write_ok = TRUE;
        while (remaining > 0 && write_ok) {
            DWORD to_read = remaining < sizeof(chunk) ? remaining : sizeof(chunk);
            DWORD did_read = 0;
            LARGE_INTEGER li; li.QuadPart = (LONGLONG)read_pos;
            SetFilePointerEx(hf, li, NULL, FILE_BEGIN);
            if (!ReadFile(hf, chunk, to_read, &did_read, NULL) || did_read == 0) break;
            DWORD written = 0;
            if (!WriteFile(hout, chunk, did_read, &written, NULL) || written != did_read)
                write_ok = FALSE;
            read_pos += did_read;
            remaining -= did_read;
        }
        CloseHandle(hout);

        /* Store in file list */
        if (files) {
            files[file_count] = (wchar_t *)malloc((wcslen(dest_path) + 1) * sizeof(wchar_t));
            if (files[file_count]) {
                wcscpy(files[file_count], dest_path);
                file_count++;
            }
        }

        /* Report progress */
        SendMessage(hDlg, WM_INSTALL_PROGRESS, (WPARAM)(i + 1), (LPARAM)total);

        /* Update status label with filename (just the base name) */
        wchar_t *base = wcsrchr(fname_w, L'\\');
        base = base ? base + 1 : fname_w;
        SetDlgItemTextW(hDlg, IDC_STATUS, base);
    }

    CloseHandle(hf);
    *out_files = files;
    *out_count = file_count;
    return !g_cancelled;
}

/* ── Shortcut helpers ─────────────────────────────────────────────────── */

static void create_shortcut(const wchar_t *target, const wchar_t *link_path,
                            const wchar_t *working_dir)
{
    CoInitialize(NULL);
    IShellLinkW *psl = NULL;
    HRESULT hr = CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER,
                                  &IID_IShellLinkW, (void **)&psl);
    if (FAILED(hr)) { CoUninitialize(); return; }

    IShellLinkW_SetPath(psl, target);
    IShellLinkW_SetWorkingDirectory(psl, working_dir);

    IPersistFile *ppf = NULL;
    hr = IShellLinkW_QueryInterface(psl, &IID_IPersistFile, (void **)&ppf);
    if (SUCCEEDED(hr)) {
        IPersistFile_Save(ppf, link_path, TRUE);
        IPersistFile_Release(ppf);
    }
    IShellLinkW_Release(psl);
    CoUninitialize();
}

/* ── Registry helpers ─────────────────────────────────────────────────── */

static void register_uninstall(const wchar_t *install_dir,
                                const wchar_t *uninstall_exe)
{
    HKEY hkey;
    const wchar_t *key_path =
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinZapp";
    if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, key_path, 0, NULL,
                        REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hkey, NULL) != ERROR_SUCCESS)
        return;

    RegSetValueExW(hkey, L"DisplayName", 0, REG_SZ,
                   (BYTE *)L"WinZapp", sizeof(L"WinZapp"));
    RegSetValueExW(hkey, L"UninstallString", 0, REG_SZ,
                   (BYTE *)uninstall_exe,
                   (DWORD)((wcslen(uninstall_exe) + 1) * sizeof(wchar_t)));
    RegSetValueExW(hkey, L"InstallLocation", 0, REG_SZ,
                   (BYTE *)install_dir,
                   (DWORD)((wcslen(install_dir) + 1) * sizeof(wchar_t)));
    RegSetValueExW(hkey, L"DisplayVersion", 0, REG_SZ,
                   (BYTE *)L"1.0.0", sizeof(L"1.0.0"));
    RegSetValueExW(hkey, L"Publisher", 0, REG_SZ,
                   (BYTE *)L"WinZapp", sizeof(L"WinZapp"));
    DWORD no_modify = 1;
    RegSetValueExW(hkey, L"NoModify", 0, REG_DWORD,
                   (BYTE *)&no_modify, sizeof(DWORD));
    RegSetValueExW(hkey, L"NoRepair", 0, REG_DWORD,
                   (BYTE *)&no_modify, sizeof(DWORD));
    RegCloseKey(hkey);
}

/* ── Write installed files list ───────────────────────────────────────── */

static void write_file_list(const wchar_t *install_dir,
                             wchar_t **files, int count)
{
    wchar_t list_path[MAX_PATH];
    swprintf(list_path, MAX_PATH, L"%s\\installed_files.dat", install_dir);
    FILE *f = _wfopen(list_path, L"w, ccs=UTF-8");
    if (!f) return;
    for (int i = 0; i < count; i++)
        fwprintf(f, L"%s\n", files[i]);
    fclose(f);
}

/* ── Install thread ───────────────────────────────────────────────────── */

static DWORD WINAPI install_thread(LPVOID param)
{
    InstallParams *p = (InstallParams *)param;

    /* Create destination directory */
    SHCreateDirectoryExW(NULL, p->install_dir, NULL);

    wchar_t **files = NULL;
    int file_count = 0;
    BOOL ok = extract_all(g_hDlg, p->install_dir, &files, &file_count);

    if (!ok || g_cancelled) {
        if (files) {
            for (int i = 0; i < file_count; i++) free(files[i]);
            free(files);
        }
        free(p);
        if (!g_cancelled) {
            wchar_t *err = _wcsdup(L"Extração falhou.");
            SendMessage(g_hDlg, WM_INSTALL_ERROR, 0, (LPARAM)err);
        }
        return 0;
    }

    /* Shortcuts */
    wchar_t exe_path[MAX_PATH];
    swprintf(exe_path, MAX_PATH, L"%s\\app\\WinZapp.exe", p->install_dir);

    if (p->desktop_sc) {
        wchar_t desktop[MAX_PATH];
        SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, desktop);
        wchar_t link[MAX_PATH];
        swprintf(link, MAX_PATH, L"%s\\WinZapp.lnk", desktop);
        create_shortcut(exe_path, link, p->install_dir);
    }

    if (p->startmenu_sc) {
        wchar_t programs[MAX_PATH];
        SHGetFolderPathW(NULL, CSIDL_COMMON_PROGRAMS, NULL, 0, programs);
        wchar_t link[MAX_PATH];
        swprintf(link, MAX_PATH, L"%s\\WinZapp.lnk", programs);
        create_shortcut(exe_path, link, p->install_dir);
    }

    /* Uninstaller path */
    wchar_t uninstall_exe[MAX_PATH];
    swprintf(uninstall_exe, MAX_PATH, L"%s\\uninstall.exe", p->install_dir);

    /* Registry */
    register_uninstall(p->install_dir, uninstall_exe);

    /* File list */
    write_file_list(p->install_dir, files, file_count);

    for (int i = 0; i < file_count; i++) free(files[i]);
    free(files);
    free(p);

    SendMessage(g_hDlg, WM_INSTALL_DONE, 0, 0);
    return 0;
}

/* ── Dialog procedure ─────────────────────────────────────────────────── */

static INT_PTR CALLBACK DlgProc(HWND hDlg, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg) {
    case WM_INITDIALOG: {
        g_hDlg = hDlg;

        /* Default install path: %LOCALAPPDATA%\WinZapp */
        wchar_t local_app[MAX_PATH];
        if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, local_app))) {
            wchar_t def_path[MAX_PATH];
            swprintf(def_path, MAX_PATH, L"%s\\WinZapp", local_app);
            SetDlgItemTextW(hDlg, IDC_INSTALL_PATH, def_path);
        }

        /* Check both shortcut checkboxes by default */
        CheckDlgButton(hDlg, IDC_DESKTOP_SC,   BST_CHECKED);
        CheckDlgButton(hDlg, IDC_STARTMENU_SC, BST_CHECKED);

        /* Initialise progress bar range; we'll set max when we know entry count */
        SendDlgItemMessage(hDlg, IDC_PROGRESS, PBM_SETRANGE32, 0, 100);
        return TRUE;
    }

    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDC_BROWSE: {
            BROWSEINFOW bi = {0};
            bi.hwndOwner = hDlg;
            bi.lpszTitle = L"Selecione a pasta de instalação";
            bi.ulFlags   = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
            LPITEMIDLIST pidl = SHBrowseForFolderW(&bi);
            if (pidl) {
                wchar_t path[MAX_PATH];
                if (SHGetPathFromIDListW(pidl, path))
                    SetDlgItemTextW(hDlg, IDC_INSTALL_PATH, path);
                CoTaskMemFree(pidl);
            }
            return TRUE;
        }

        case IDC_INSTALL: {
            wchar_t install_dir[MAX_PATH];
            GetDlgItemTextW(hDlg, IDC_INSTALL_PATH, install_dir, MAX_PATH);
            if (!install_dir[0]) {
                MessageBoxW(hDlg, L"Por favor, selecione uma pasta de instalação.",
                            L"WinZapp", MB_OK | MB_ICONWARNING);
                return TRUE;
            }

            /* Disable install/cancel buttons while installing */
            EnableWindow(GetDlgItem(hDlg, IDC_INSTALL), FALSE);
            EnableWindow(GetDlgItem(hDlg, IDC_CANCEL),  FALSE);
            EnableWindow(GetDlgItem(hDlg, IDC_BROWSE),  FALSE);

            InstallParams *params = (InstallParams *)malloc(sizeof(InstallParams));
            wcsncpy(params->install_dir, install_dir, MAX_PATH - 1);
            params->desktop_sc   = IsDlgButtonChecked(hDlg, IDC_DESKTOP_SC)   == BST_CHECKED;
            params->startmenu_sc = IsDlgButtonChecked(hDlg, IDC_STARTMENU_SC) == BST_CHECKED;

            HANDLE hThread = CreateThread(NULL, 0, install_thread, params, 0, NULL);
            if (hThread) CloseHandle(hThread);
            return TRUE;
        }

        case IDC_CANCEL:
            g_cancelled = TRUE;
            EndDialog(hDlg, IDCANCEL);
            return TRUE;
        }
        break;

    case WM_INSTALL_PROGRESS: {
        int done  = (int)wParam;
        int total = (int)lParam;
        if (total > 0) {
            SendDlgItemMessage(hDlg, IDC_PROGRESS, PBM_SETRANGE32, 0, total);
            SendDlgItemMessage(hDlg, IDC_PROGRESS, PBM_SETPOS, done, 0);
        }
        return TRUE;
    }

    case WM_INSTALL_DONE:
        MessageBoxW(hDlg, L"WinZapp foi instalado com sucesso!",
                    L"Instalação concluída", MB_OK | MB_ICONINFORMATION);
        EndDialog(hDlg, IDOK);
        return TRUE;

    case WM_INSTALL_ERROR: {
        wchar_t *err = (wchar_t *)lParam;
        wchar_t msg_buf[512];
        swprintf(msg_buf, 512, L"Ocorreu um erro durante a instalação:\n%s", err ? err : L"");
        free(err);
        MessageBoxW(hDlg, msg_buf, L"Erro de instalação", MB_OK | MB_ICONERROR);
        EndDialog(hDlg, IDABORT);
        return TRUE;
    }

    case WM_CLOSE:
        g_cancelled = TRUE;
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

    INITCOMMONCONTROLSEX icc = { sizeof(icc), ICC_PROGRESS_CLASS };
    InitCommonControlsEx(&icc);

    DialogBoxW(hInstance, MAKEINTRESOURCEW(IDD_INSTALL), NULL, DlgProc);
    return 0;
}
