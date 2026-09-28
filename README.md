# DeepLoyerFree

A small desktop app that watches your build folders and automatically copies the
artifacts (`.war`, `.jar`, …) where they need to go, for example from Maven's
`target/` folder into Tomcat's `webapps/`.

No more copying files by hand after every build: compile, and a few seconds later
the new file is in place.

- Multiple independent **environments**, each with its own source, file filter and destination
- **Wildcards** in file names, so `geneweb-engine-*.jar` keeps working when the version changes
- Waits until the **build has finished** before copying, and copies **atomically**
  (temporary file + rename), so Tomcat never picks up a half-written file
- Optionally keeps **only the latest version** in the destination
- Runs in the **system tray**, with notifications, and can **start at login**
- Works on **Linux** and **Windows**

> The user interface is in Italian.

## Download

Ready-to-run executables are available on the
[Releases](../../releases) page. Nothing else needs to be installed.

| System  | File                           | How to start it                                   |
| ------- | ------------------------------ | ------------------------------------------------- |
| Linux   | `DeepLoyerFree-linux-x86_64`        | `chmod +x DeepLoyerFree-linux-x86_64`, then double-click it or run it |
| Windows | `DeepLoyerFree-windows-x86_64.exe`  | Double-click it                                   |

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

1. Click **Aggiungi** to create an environment.
2. Fill in the form:

   | Field                   | Meaning                                                    | Example                         |
   | ----------------------- | ---------------------------------------------------------- | ------------------------------- |
   | Nome                    | A name you choose                                          | `Appalti`                       |
   | Cartella sorgente       | Folder where the build writes the file                     | `~/Projects/Appalti/target`     |
   | File da copiare         | File name, `*` and `?` allowed                              | `Appalti.war`, `geneweb-engine-*.jar` |
   | Escludi                 | Optional, comma-separated patterns to skip                  | `*-sources.jar, *-javadoc.jar`  |
   | Cartella destinazione   | Where the file is copied                                    | `~/tomcat/webapps`              |
   | Attesa fine build       | How long the file must stay unchanged before it is copied  | `3 s`                           |

   The bottom of the form shows which file would be copied right now, so you can check the
   filter immediately.
3. Save. From now on, every time the build produces a newer file, it is copied automatically.

The table shows the status of each environment and the time of the last copy; the log below
shows every operation. **Copia adesso** forces a copy of the selected environment, and the
checkbox in the first column enables or disables it.

### Keep only the latest version

When the version is part of the file name (e.g. `geneweb-engine-2.60.0.jar`), tick
**Tieni solo l'ultima versione**: after each copy, older files matching the filter are
removed from the destination. For safety, this option requires a filter that starts with a
fixed name, so a pattern like `*.jar` can never wipe other files.

### Start automatically

From the **Opzioni** menu:

- **Avvia all'accesso** starts DeepLoyerFree in the tray every time you log in
- **Aggiungi al menu applicazioni** (Linux) / **Aggiungi al menu Start** (Windows) adds a launcher

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
Linux. The GitHub Actions workflow in `.github/workflows/release.yml` does both: push a tag
such as `v1.0.0` and the executables are attached to a new release.

## Troubleshooting

**Linux: `could not load the Qt platform plugin "xcb"`**
A system library is missing. On Debian, Ubuntu or Mint: `sudo apt install libxcb-cursor0`.

**Linux: `permission denied` when starting a script or the executable**
The execute permission was lost during download: `chmod +x run.sh build.sh DeepLoyerFree-linux-x86_64`.

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

- Executables: Linux x86_64 (glibc 2.35 or newer) or Windows 10/11
- From source: Python 3.10+ and PySide6 6.5+, or just uv