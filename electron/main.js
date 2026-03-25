const { app, BrowserWindow, dialog, Menu, shell } = require('electron');
const { spawn, execSync, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

// ---- PATHS ----
const isDev = !app.isPackaged;
const RES = isDev ? __dirname : process.resourcesPath;
const appRoot = path.join(RES, 'app');

const PORT = 7751;
let serverProcess = null;
let mainWindow = null;
let isQuitting = false;

// ---- FIND PYTHON ----
function findPython() {
  // 1. Bundled Python (ships with the app — no install needed)
  const bundledUnix = path.join(RES, 'python', 'bin', 'python3');
  if (fs.existsSync(bundledUnix)) return bundledUnix;

  const bundledWin = path.join(RES, 'python', 'python.exe');
  if (fs.existsSync(bundledWin)) return bundledWin;

  // 2. Dev mode — check for venv in app root
  if (isDev) {
    const venvPy = path.join(appRoot, '..', '.venv', 'bin', 'python3');
    if (fs.existsSync(venvPy)) return venvPy;
    const venvPyWin = path.join(appRoot, '..', '.venv', 'Scripts', 'python.exe');
    if (fs.existsSync(venvPyWin)) return venvPyWin;
  }

  // 3. System Python as last resort
  for (const cmd of ['python3', 'python']) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { timeout: 5000 }).toString().trim();
      const match = ver.match(/(\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 10))) {
        return cmd;
      }
    } catch {}
  }

  return null;
}

// ---- PORT CHECK ----
function isPortInUse(port) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once('error', () => resolve(true));
    s.once('listening', () => { s.close(); resolve(false); });
    s.listen(port, '127.0.0.1');
  });
}

// ---- WRITABLE APP DATA ----
// On first run, copy bundled app to a writable location so memories/conversations persist
function getWritableAppDir() {
  const dataDir = path.join(app.getPath('userData'), 'app-data');
  return dataDir;
}

function ensureWritableApp() {
  const dataDir = getWritableAppDir();
  const marker = path.join(dataDir, '.initialized');

  if (fs.existsSync(marker)) {
    // Already initialized — just make sure core files are updated from bundle
    // (personality, templates, etc. might have been updated in a new version)
    const updateFiles = ['app.py', 'personality.md', 'templates', 'static', 'requirements.txt'];
    for (const f of updateFiles) {
      const src = path.join(appRoot, f);
      const dst = path.join(dataDir, f);
      if (fs.existsSync(src)) {
        if (fs.statSync(src).isDirectory()) {
          copyDirSync(src, dst);
        } else {
          fs.copyFileSync(src, dst);
        }
      }
    }
    return dataDir;
  }

  // First run — copy everything from bundled app
  console.log('First run — setting up app data...');
  copyDirSync(appRoot, dataDir);

  // Create data directories
  for (const dir of ['.memories', '.conversations', '.homework', '.quizzes', '.tts_cache', 'people']) {
    const p = path.join(dataDir, dir);
    if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
  }

  // Copy .env.example to .env if no .env exists
  const envDst = path.join(dataDir, '.env');
  const bundledEnv = path.join(RES, 'bundled.env');
  const envExample = path.join(dataDir, '.env.example');
  if (!fs.existsSync(envDst)) {
    // Prefer bundled.env (has real keys) over .env.example
    if (fs.existsSync(bundledEnv)) {
      fs.copyFileSync(bundledEnv, envDst);
    } else if (fs.existsSync(envExample)) {
      fs.copyFileSync(envExample, envDst);
    }
  }

  fs.writeFileSync(marker, new Date().toISOString());
  return dataDir;
}

function copyDirSync(src, dst) {
  if (!fs.existsSync(dst)) fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const dstPath = path.join(dst, entry.name);
    if (entry.isDirectory()) {
      copyDirSync(srcPath, dstPath);
    } else {
      fs.copyFileSync(srcPath, dstPath);
    }
  }
}

// ---- CHECK ENV ----
function checkEnv(appDir) {
  const envPath = path.join(appDir, '.env');
  if (!fs.existsSync(envPath)) {
    // Try to copy from bundled
    const bundledEnv = path.join(RES, 'bundled.env');
    if (fs.existsSync(bundledEnv)) {
      fs.copyFileSync(bundledEnv, envPath);
      return true;
    }
    return false;
  }
  const content = fs.readFileSync(envPath, 'utf8');
  // Check that at least OpenAI key is set (not placeholder)
  if (content.includes('YOUR_KEY_HERE')) return false;
  if (/OPENAI_API_KEY=sk-/.test(content)) return true;
  return false;
}

// ---- INSTALL DEPS ----
function installDeps(pythonPath, appDir) {
  const reqPath = path.join(appDir, 'requirements.txt');
  if (!fs.existsSync(reqPath)) return true;

  // Quick check — try importing core deps
  try {
    execFileSync(pythonPath, ['-c', 'import flask; import openai'], {
      cwd: appDir,
      stdio: 'ignore',
      timeout: 15000,
    });
    return true;
  } catch {}

  // Install
  try {
    execFileSync(pythonPath, ['-m', 'pip', 'install', '-r', 'requirements.txt', '--quiet', '--disable-pip-version-check'], {
      cwd: appDir,
      stdio: 'inherit',
      timeout: 180000,
    });
    return true;
  } catch (e) {
    console.error('Dep install failed:', e.message);
    return false;
  }
}

// ---- START SERVER ----
async function startServer(pythonPath, appDir) {
  if (await isPortInUse(PORT)) {
    console.log(`Port ${PORT} in use — assuming server running`);
    return true;
  }

  return new Promise((resolve) => {
    serverProcess = spawn(pythonPath, ['app.py'], {
      cwd: appDir,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let started = false;
    const timeout = setTimeout(() => {
      if (!started) resolve(false);
    }, 45000);

    const checkOutput = (data) => {
      const text = data.toString();
      console.log('[srv]', text.trim());
      if (!started && (text.includes('Running on') || text.includes('Starting') || text.includes('port'))) {
        started = true;
        clearTimeout(timeout);
        setTimeout(() => resolve(true), 2000);
      }
    };

    serverProcess.stdout.on('data', checkOutput);
    serverProcess.stderr.on('data', checkOutput);
    serverProcess.on('exit', (code) => {
      console.log(`Server exited: ${code}`);
      serverProcess = null;
      if (!started) { clearTimeout(timeout); resolve(false); }
    });
  });
}

// ---- WINDOW ----
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 400,
    minHeight: 600,
    title: 'WickMind',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#06081a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
  });

  mainWindow.loadFile(path.join(__dirname, 'splash.html'));
  mainWindow.show();

  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

function splash(msg) {
  if (mainWindow) {
    mainWindow.webContents.executeJavaScript(
      `document.getElementById('status').textContent = ${JSON.stringify(msg)};`
    ).catch(() => {});
  }
}

// ---- MAIN ----
app.whenReady().then(async () => {
  createWindow();
  splash('Starting WickMind...');

  // 1. Find Python
  splash('Checking Python...');
  const pythonPath = findPython();
  if (!pythonPath) {
    const action = dialog.showMessageBoxSync(mainWindow, {
      type: 'error',
      title: 'Python Not Found',
      message: 'WickMind includes Python but it wasn\'t found.',
      detail: 'This shouldn\'t happen with a normal install.\n\n' +
        'As a fallback, you can install Python manually from python.org ' +
        '(version 3.10 or newer), then restart WickMind.',
      buttons: ['Download Python', 'Quit'],
    });
    if (action === 0) shell.openExternal('https://www.python.org/downloads/');
    app.quit();
    return;
  }

  // 2. Set up writable app directory
  splash('Setting up...');
  let appDir;
  try {
    appDir = ensureWritableApp();
  } catch (e) {
    dialog.showErrorBox('Setup Error', `Failed to initialize app data:\n${e.message}`);
    app.quit();
    return;
  }

  // 3. Check API keys (bundled.env has them pre-configured)
  splash('Checking configuration...');
  if (!checkEnv(appDir)) {
    const envPath = path.join(appDir, '.env');
    const action = dialog.showMessageBoxSync(mainWindow, {
      type: 'info',
      title: 'API Keys Needed',
      message: 'Steve needs API keys to work.',
      detail:
        'The API keys may have expired or are missing.\n\n' +
        'Open the .env file and add:\n' +
        '🧠 OPENAI_API_KEY → platform.openai.com\n' +
        '🎙️ ELEVENLABS_API_KEY → elevenlabs.io\n\n' +
        'Save the file, then reopen WickMind.',
      buttons: ['Open .env File', 'Quit'],
    });
    if (action === 0) {
      shell.openPath(envPath);
    }
    app.quit();
    return;
  }

  // 4. Install dependencies
  splash('Installing dependencies (first run only)...');
  const depsOk = installDeps(pythonPath, appDir);
  if (!depsOk) {
    dialog.showErrorBox('Setup Error',
      'Failed to install Python packages.\n\n' +
      'Check your internet connection and try again.\n\n' +
      `Python: ${pythonPath}\nApp: ${appDir}`);
    app.quit();
    return;
  }

  // 5. Start server
  splash('Waking up Steve...');
  const started = await startServer(pythonPath, appDir);
  if (!started) {
    dialog.showErrorBox('Server Error',
      'Steve failed to start.\n\n' +
      'Check the console (View → Toggle Developer Tools) for details.');
    app.quit();
    return;
  }

  // 6. Load
  splash('Almost there...');
  setTimeout(() => {
    if (mainWindow) mainWindow.loadURL(`http://127.0.0.1:${PORT}`);
  }, 500);

  // Menu
  const appMenu = [
    {
      label: 'WickMind',
      submenu: [
        { label: 'About WickMind', role: 'about' },
        { type: 'separator' },
        {
          label: 'Edit Family Memories',
          click: () => shell.openPath(path.join(appDir, 'family.md')),
        },
        {
          label: 'Edit Personality',
          click: () => shell.openPath(path.join(appDir, 'personality.md')),
        },
        {
          label: 'Edit API Keys',
          click: () => shell.openPath(path.join(appDir, '.env')),
        },
        { type: 'separator' },
        {
          label: 'Open Data Folder',
          click: () => shell.openPath(appDir),
        },
        { type: 'separator' },
        {
          label: 'Quit WickMind',
          accelerator: 'CmdOrCtrl+Q',
          click: () => { isQuitting = true; app.quit(); },
        },
      ],
    },
    { label: 'Edit', submenu: [
      { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
      { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
    ]},
    { label: 'View', submenu: [
      { role: 'reload' },
      { role: 'toggleDevTools' },
      { type: 'separator' },
      { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'resetZoom' },
    ]},
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(appMenu));
});

app.on('before-quit', () => {
  isQuitting = true;
  if (serverProcess) {
    serverProcess.kill('SIGTERM');
    // Give it a moment, then force
    setTimeout(() => {
      if (serverProcess) {
        try { serverProcess.kill('SIGKILL'); } catch {}
      }
    }, 3000);
    serverProcess = null;
  }
});

app.on('activate', () => {
  if (mainWindow) mainWindow.show();
  else createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
