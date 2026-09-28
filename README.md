# DeepLoyerFree

A small desktop app that watches your build folders and automatically copies the
artifacts (`.war`, `.jar`, …) where they need to go, for example from Maven's
`target/` folder into Tomcat's `webapps/`.

No more copying files by hand after every build: compile, and a few seconds later
the new file is in place.

- Multiple independent **environments**, each with its own source, file filter and destination
- **Wildcards** in file names, so `my-library-*.jar` keeps working when the version changes
- Waits until the **build has finished** before copying, and copies **atomically**
  (temporary file + rename), so Tomcat never picks up a half-written file
- Optionally keeps **only the latest version** in the destination
- Runs in the **system tray**, with notifications, and can **start at login**
- Works on **Linux** and **Windows**, with experimental **macOS** support

## Download

Pick the package for your system. The links always point to the latest release, and nothing
else needs to be installed.

| System                | Download                                                                                     |
| --------------------- | -------------------------------------------------------------------------------------------- |
| Linux (x86_64)        | [DeepLoyerFree-linux-x86_64.tar.gz](../../releases/latest/download/DeepLoyerFree-linux-x86_64.tar.gz) |
| Windows 10/11         | [DeepLoyerFree-windows-x86_64.exe](../../releases/latest/download/DeepLoyerFree-windows-x86_64.exe)   |
| macOS (Apple Silicon) | [DeepLoyerFree-macos-arm64.zip](../../releases/latest/download/DeepLoyerFree-macos-arm64.zip)         |

All versions are listed on the [Releases](../../releases) page.

**Linux**: extract the archive and start the program:

```bash
tar -xzf DeepLoyerFree-linux-x86_64.tar.gz
./DeepLoyerFree
```

Then use **Options → Add to applications menu** to get a menu entry with its icon.

**Windows**: double-click `DeepLoyerFree-windows-x86_64.exe`. Use **Options → Add to Start menu**
to find it in the Start menu from then on.

**macOS**: unzip the file and move `DeepLoyerFree.app` to *Applications*. The first time,
right-click it and choose *Open*, because the app is not signed. macOS support is experimental:
*Start at login* and the menu launcher are not available there.

The executable takes a couple of seconds to open: it unpacks itself at every start.

## Run from source

Clone the repository, then use the launcher for your system:

```bash
git clone https://github.com/<your-user>/deeployerfree.git
cd deeployerfree
./run.sh        # Linux
run.bat         # Windows
```

The launcher uses [uv](https://docs.astral.sh/uv/) if it is installed, which downloads the
right dependencies by itself. Otherwise it creates a local `.venv` with Python 3.10+ and
installs `requirements.txt` on the first run.

You can also start it directly:

```bash
uv run deeployerfree.py                                    # with uv
pip install -r requirements.txt && python deeployerfree.py # with plain Python
```

Add `--tray` to start minimized to the system tray.

## How to use it

1. Click **Add** to create an environment.
2. Fill in the form:

   | Field               | Meaning                                                    | Example                              |
   | ------------------- | ---------------------------------------------------------- | ------------------------------------ |
   | Name                | A name you choose                                          | `My App`                             |
   | Source folder       | Folder where the build writes the file                     | `~/projects/my-app/target`           |
   | File to copy        | File name, `*` and `?` allowed                             | `my-app.war`, `my-library-*.jar`     |
   | Exclude             | Optional, comma-separated patterns to skip                 | `*-sources.jar, *-javadoc.jar`       |
   | Destination folder  | Where the file is copied                                   | `~/tomcat/webapps`                   |
   | Wait for build end  | How long the file must stay unchanged before it is copied  | `3 s`                                |

   The bottom of the form shows which file would be copied right now, so you can check the
   filter immediately.
3. Save. From now on, every time the build produces a newer file, it is copied automatically.

The table shows the status of each environment and the time of the last copy; the log below
shows every operation. **Copy now** forces a copy of the selected environment, and the
checkbox in the first column enables or disables it.

### Keep only the latest version

When the version is part of the file name (e.g. `my-library-2.1.0.jar`), tick
**Keep only the latest version**: after each copy, older files matching the filter are
removed from the destination. For safety, this option requires a filter that starts with a
fixed name, so a pattern like `*.jar` can never wipe other files.

### Start automatically

From the **Options** menu:

- **Start at login** starts DeepLoyerFree in the tray every time you log in
- **Add to applications menu** (Linux) / **Add to Start menu** (Windows) adds a launcher

Both remember the current location of the program: if you move it, untick and tick
the option again.

## Configuration

Environments are saved automatically in:

- Linux: `~/.config/deeployerfree/config.json`
- Windows: `%APPDATA%\DeepLoyerFree\config.json`

The file is plain JSON, so it can be backed up or copied to another machine.

## Build the executable yourself

With [uv](https://docs.astral.sh/uv/) installed:

```bash
./build.sh      # Linux   -> dist/DeepLoyerFree
build.bat       # Windows -> dist\DeepLoyerFree.exe
```

PyInstaller cannot cross-compile: build the Windows executable on Windows and the Linux one on
Linux. The GitHub Actions workflow in `.github/workflows/release.yml` builds all three packages on
GitHub's servers: push a tag such as `v1.0.0` and they are attached to a new release.

## Troubleshooting

**Linux: `could not load the Qt platform plugin "xcb"`**
A system library is missing. On Debian, Ubuntu or Mint: `sudo apt install libxcb-cursor0`.

**Linux: `permission denied` when starting a script or the executable**
The execute permission was lost during download: `chmod +x run.sh build.sh DeepLoyerFree`.

**Windows: SmartScreen or Defender blocks the executable**
Unsigned PyInstaller executables are sometimes flagged. Choose *More info → Run anyway*,
or run from source instead.

**Windows: the copy fails because the file is in use**
Tomcat on Windows can keep files in `webapps` locked. DeepLoyerFree reports the error and retries at
the next build. To avoid it, set `antiResourceLocking="true"` on the `<Context>` element in
Tomcat's `conf/context.xml`.

**The tray icon does not appear**
Some desktops (e.g. GNOME without extensions) have no system tray. DeepLoyerFree then works as a
normal window: closing it quits the app.

## Requirements

- Executables: Linux x86_64 (glibc 2.35 or newer), Windows 10/11 or macOS on Apple Silicon
- From source: Python 3.10+ and PySide6 6.5+, or just uv