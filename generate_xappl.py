import os
import sys

def build_xml(staging_dir, output_xappl):
    # Base headers
    xml_lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<Configuration>',
        '  <Output diagnosticMode="false" includeRuntimeDotNetImage="false" allowFullIsolation="false" enableSync="false" enableAutoUpdate="false" showLaunchSettings="false" isolationLevel="WriteCopy" hub="https://turbo.net" isolationOptions="MergeUser" />',
        '  <VirtualizationSettings suppressBranding="True" deleteSandbox="False" shutdownProcessTree="False" enhancedDEPCompatibility="False" notifyProcessStarts="False" enableLegacySecurityPassthrough="False" trimUACManifest="False" forceFIPSCompliance="False" forceReadShareFiles="False" isolateWindowClasses="False" readOnlyVirtualization="False" disableXenocodeCommandLine="False" suppressSandboxCollisionCheck="False" subsystem="Inherit" targetArchitecture="x64" sandboxPath="@APPDATALOCAL@\\WzT" exeOptimization="False" compressPayload="False" forceIndicateRunningElevated="False" launchChildProcsAsUser="True" enableDRMCompatibility="False" faultExecutablesIntoSandbox="True" minStackSize="0" minSandboxSpaceAvail="-1" honorWow6464AccessFlag="True" suppressPopups="False" hideShellWindow="False" isDriverSVM="False" forceEntryLayerIsolation="False" stubExeCachePath="" spoonCachePath="" waitForChildOnly="True" httpUrlPassthrough="False" mergeStartupDir="False" allowGlobalWindowHooks="False" breakIdenticalSendMessageRecursion="False" extendedWinXPCompatibility="False" isolateProcessNames="False" isolateNonSystemDrives="False" isolateNetworkShares="False" disableProxySupportForRouteMaps="False" isolateDDE="False" aggressiveRegistrySandboxCachePolicy="False" chromiumSupport="False" handleExplorerShellEx="False" useDllInjection="False" isolateComActiveObjects="False" isolateProcessEnumeration="False" isolateDragDrop="False">',
        '    <ChildProcessVirtualization spawnVm="true" spawnExternalComServers="false" />',
        '  </VirtualizationSettings>',
        '  <StartupFiles>',
        '    <StartupFile node="@SYSDRIVE@\\WinZapp\\WinZapp.exe" tag="" commandLine="" default="True" architecture="AnyCpu" />',
        '  </StartupFiles>',
        '  <Layers>',
        '    <Layer name="Default">',
        '      <Filesystem>',
        '        <Directory name="@APPDATA@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@APPDATACOMMON@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@APPDATALOCAL@" isolation="Merge" readOnly="False" hide="False" noSync="True" />',
        '        <Directory name="@APPDATALOCALLOW@" isolation="Merge" readOnly="False" hide="False" noSync="True" />',
        '        <Directory name="@DESKTOP@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@DOCUMENTS@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@DOWNLOADS@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@DRIVE_C@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@PROGRAMFILES@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@PROGRAMFILESX86@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Directory name="@SYSDRIVE@" isolation="Merge" readOnly="False" hide="False" noSync="False">',
        '          <Directory name="WinZapp" isolation="Full" readOnly="False" hide="False" noSync="False">'
    ]

    # Recursive directory/file tag builder
    def add_dir_contents(current_dir, indent_level):
        indent = '  ' * indent_level
        try:
            items = os.listdir(current_dir)
        except Exception:
            return
        
        # Sort items: directories first, then files
        dirs = []
        files = []
        for item in items:
            full_path = os.path.join(current_dir, item)
            if os.path.isdir(full_path):
                dirs.append(item)
            else:
                files.append(item)
                
        # Write files
        for f in files:
            rel_path = os.path.relpath(os.path.join(current_dir, f), staging_dir).replace('/', '\\')
            source_path = f'.\\Files\\Default\\@SYSDRIVE@\\WinZapp\\{rel_path}'
            # Escape XML entities in name and source
            xml_name = f.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            xml_source = source_path.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            xml_lines.append(f'{indent}<File name="{xml_name}" isolation="Full" readOnly="False" hide="False" source="{xml_source}" upgradeable="True" precacheable="True" />')
            
        # Write subdirectories
        for d in dirs:
            xml_d = d.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            xml_lines.append(f'{indent}<Directory name="{xml_d}" isolation="Full" readOnly="False" hide="False" noSync="False">')
            add_dir_contents(os.path.join(current_dir, d), indent_level + 1)
            xml_lines.append(f'{indent}</Directory>')

    add_dir_contents(staging_dir, 6)

    # Closing XML tags
    xml_lines.extend([
        '          </Directory>',
        '        </Directory>',
        '      </Filesystem>',
        '      <Registry>',
        '        <Key name="@HKCR@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Key name="@HKCU@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Key name="@HKLM@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '        <Key name="@HKU@" isolation="Merge" readOnly="False" hide="False" noSync="False" />',
        '      </Registry>',
        '    </Layer>',
        '  </Layers>',
        '  <OutputFile value="WinZappContainer.exe" />',
        '  <ProjectType value="Application" />',
        '  <FilesLocation value=".\\Files" />',
        '</Configuration>'
    ])

    with open(output_xappl, 'w', encoding='utf-8') as f:
        f.write('\n'.join(xml_lines))

if __name__ == '__main__':
    staging = os.path.join("build", "staging_pyinstaller")
    output = "WinZapp.xappl"
    if len(sys.argv) > 1:
        staging = sys.argv[1]
    if len(sys.argv) > 2:
        output = sys.argv[2]
    build_xml(staging, output)
    print(f"Generated {output} successfully from {staging}")
