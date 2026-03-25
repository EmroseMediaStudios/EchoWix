const { app, BrowserWindow, dialog, Menu, Tray, shell } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

// ---- PATHS ----
const isDev = !app.isPackaged;
const appRoot = isDev
  ? path.join(__dirname, '..')
  : path.join(process.resourcesPath, 'app');

const PORT = 7751;
let serverProcess = null;
let mainWindow = null;
let tray = null;
let isQuitting = false;

// ---- FIND PYTHON ----
function findPython() {
  // Check for bundled Python first
  const bundled = path.join(appRoot, 'python', 'bin', 'python3');
  if (fs.existsSync(bundled)) return bundled;

  // Windows bundled
  const bundledWin = path.join(appRoot, 'python', 'python.exe');
  if (fs.existsSync(bundledWin)) return bundledWin;

  // Check for venv
  const venvPy = path.join(appRoot, '.venv', 'bin', 'python3');
  if (fs.existsSync(venvPy)) return venvPy;
  const venvPyWin = path.join(appRoot, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venvPyWin)) return venvPyWin;

  // System Python
  try {
    execSync('python3 --version', { stdio: 'ignore' });
    return 'python3';
  } catch {
    try {
      execSync('python --version', { stdio: 'ignore' });
      return 'python';
    } catch {
      return null;
    }
  }
}

// ---- CHECK PORT ----
function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(true));
    server.once('listening', () => { server.close(); resolve(false); });
    server.listen(port, '127.0.0.1');
  });
}

// ---- ENV FILE ----
function ensureEnv() {
  const envPath = path.join(appRoot, '.env');
  const examplePath = path.join(appRoot, '.env.example');

  if (!fs.existsSync(envPath)) {
    if (fs.existsSync(examplePath)) {
      fs.copyFileSync(examplePath, envPath);
    }
    return false; // needs API keys
  }

  // Check if keys are actually set
  const content = fs.readFileSync(envPath, 'utf8');
  if (content.includes('YOUR_KEY_HERE') || !content.includes('OPENAI_API_KEY=sk-')) {
    return false;
  }
  return true;
}

// ---- INSTALL DEPENDENCIES ----
function installDeps(pythonPath) {
  const reqPath = path.join(appRoot, 'requirements.txt');
  if (!fs.existsSync(reqPath)) return true;

  // Check if deps are installed by trying to import flask
  try {
    execSync(`"${pythonPath}" -c "import flask; import openai; import elevenlabs"`, {
      cwd: appRoot,
      stdio: 'ignore',
      timeout: 10000,
    });
    return true; // already installed
  } catch {
    // Need to install
    try {
      execSync(`"${pythonPath}" -m pip install -r requirements.txt --quiet`, {
        cwd: appRoot,
        stdio: 'inherit',
        timeout: 120000,
      });
      return true;
    } catch (e) {
      console.error('Failed to install dependencies:', e);
      return false;
    }
  }
}

// ---- DATA DIRECTORIES ----
function ensureDataDirs() {
  // Create data directories if they don't exist
  const dirs = ['.memories', '.conversations', '.homework', '.quizzes', '.tts_cache', 'people'];
  for (const dir of dirs) {
    const p = path.join(appRoot, dir);
    if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
  }
}

// ---- START SERVER ----
async function startServer(pythonPath) {
  const inUse = await isPortInUse(PORT);
  if (inUse) {
    console.log(`Port ${PORT} already in use — server may already be running`);
    return true;
  }

  return new Promise((resolve) => {
    serverProcess = spawn(pythonPath, ['app.py'], {
      cwd: appRoot,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let started = false;
    const timeout = setTimeout(() => {
      if (!started) {
        console.error('Server failed to start within 30 seconds');
        resolve(false);
      }
    }, 30000);

    serverProcess.stdout.on('data', (data) => {
      const text = data.toString();
      console.log('[server]', text.trim());
      if (text.includes('Starting') || text.includes('Running') || text.includes('port')) {
        if (!started) {
          started = true;
          clearTimeout(timeout);
          // Give it a moment to fully bind
          setTimeout(() => resolve(true), 1500);
        }
      }
    });

    serverProcess.stderr.on('data', (data) => {
      const text = data.toString();
      console.error('[server]', text.trim());
      // Flask debug mode prints to stderr
      if (text.includes('Running on') || text.includes('Press CTRL')) {
        if (!started) {
          started = true;
          clearTimeout(timeout);
          setTimeout(() => resolve(true), 1500);
        }
      }
    });

    serverProcess.on('exit', (code) => {
      console.log(`Server exited with code ${code}`);
      serverProcess = null;
      if (!started) {
        clearTimeout(timeout);
        resolve(false);
      }
    });
  });
}

// ---- CREATE WINDOW ----
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 400,
    minHeight: 600,
    title: 'WickMind',
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#06081a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
  });

  // Show splash while loading
  mainWindow.loadFile(path.join(__dirname, 'splash.html'));
  mainWindow.show();

  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Open external links in default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ---- CREATE SPLASH ----
function showSplash(message) {
  if (mainWindow) {
    mainWindow.webContents.executeJavaScript(
      `document.getElementById('status').textContent = "${message}";`
    ).catch(() => {});
  }
}

// ---- APP LIFECYCLE ----
app.whenReady().then(async () => {
  createWindow();
  showSplash('Starting WickMind...');

  // 1. Find Python
  showSplash('Looking for Python...');
  const pythonPath = findPython();
  if (!pythonPath) {
    dialog.showErrorBox('Python Required',
      'WickMind needs Python 3.10+ to run.\n\n' +
      'Download it from python.org and restart WickMind.');
    app.quit();
    return;
  }

  // 2. Ensure data directories
  ensureDataDirs();

  // 3. Check .env
  showSplash('Checking configuration...');
  const hasKeys = ensureEnv();
  if (!hasKeys) {
    const envPath = path.join(appRoot, '.env');
    dialog.showMessageBoxSync(mainWindow, {
      type: 'warning',
      title: 'API Keys Needed',
      message: 'WickMind needs API keys to work.',
      detail: `Please edit this file with your API keys:\n\n${envPath}\n\n` +
        'You need:\n' +
        '• OPENAI_API_KEY from platform.openai.com\n' +
        '• ELEVENLABS_API_KEY from elevenlabs.io\n\n' +
        'After adding the keys, restart WickMind.',
    });
    shell.showItemInFolder(envPath);
    app.quit();
    return;
  }

  // 4. Install dependencies
  showSplash('Checking dependencies...');
  const depsOk = installDeps(pythonPath);
  if (!depsOk) {
    dialog.showErrorBox('Setup Error',
      'Failed to install Python dependencies.\n\n' +
      'Try running this in Terminal:\n' +
      `cd "${appRoot}" && "${pythonPath}" -m pip install -r requirements.txt`);
    app.quit();
    return;
  }

  // 5. Start server
  showSplash('Starting Steve...');
  const started = await startServer(pythonPath);
  if (!started) {
    dialog.showErrorBox('Server Error',
      'WickMind server failed to start.\n\n' +
      'Check the console for errors.');
    app.quit();
    return;
  }

  // 6. Load the app
  showSplash('Almost there...');
  setTimeout(() => {
    if (mainWindow) {
      mainWindow.loadURL(`http://127.0.0.1:${PORT}`);
    }
  }, 500);

  // Set up menu
  const template = [
    {
      label: 'WickMind',
      submenu: [
        { label: 'About WickMind', role: 'about' },
        { type: 'separator' },
        {
          label: 'Open Data Folder',
          click: () => shell.openPath(appRoot),
        },
        {
          label: 'Edit Family Memories',
          click: () => shell.openPath(path.join(appRoot, 'family.md')),
        },
        {
          label: 'Edit Personality',
          click: () => shell.openPath(path.join(appRoot, 'personality.md')),
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
      { role: 'reload' }, { role: 'toggleDevTools' },
      { type: 'separator' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'resetZoom' },
    ]},
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
});

app.on('before-quit', () => {
  isQuitting = true;
  if (serverProcess) {
    serverProcess.kill('SIGTERM');
    serverProcess = null;
  }
});

app.on('activate', () => {
  if (mainWindow) {
    mainWindow.show();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
