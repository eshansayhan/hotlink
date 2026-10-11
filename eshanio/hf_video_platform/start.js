const { spawn } = require('child_process');
const path = require('path');
const os = require('os');

console.log("==========================================");
console.log("🚀 HFVideoPlatform Baslatiliyor...");
console.log("==========================================");

// 0. Eksik DLL'leri kopyala (C++ motorunun çökmesini engeller)
const fs = require('fs');
const releaseDir = path.join(__dirname, 'core_cpp', 'build', 'Release');
const depsDir = path.join(__dirname, 'core_cpp', 'build', '_deps');

const dllsToCopy = [
    { src: path.join(depsDir, 'curl-build', 'lib', 'Release', 'libcurl.dll'), dest: path.join(releaseDir, 'libcurl.dll') },
    { src: path.join(depsDir, 'glfw-build', 'src', 'Release', 'glfw3.dll'), dest: path.join(releaseDir, 'glfw3.dll') }
];

dllsToCopy.forEach(dll => {
    if (fs.existsSync(dll.src) && !fs.existsSync(dll.dest)) {
        try {
            fs.copyFileSync(dll.src, dll.dest);
            console.log(`[0/3] Eksik DLL kopyalandi: ${path.basename(dll.dest)}`);
        } catch (error) {
            console.error(`[HATA] ${path.basename(dll.dest)} kopyalanamadi: ${error.message}`);
        }
    }
});

// 1. C++ yerel video motorunu arka planda baslat
const cppPath = path.join(__dirname, 'core_cpp', 'build', 'Release', 'HFVideoPlatform.exe');
console.log(`[1/2] C++ Motoru Baslatiliyor... (${cppPath})`);

const cppEngine = spawn(cppPath, ['--background'], { stdio: 'pipe' });
cppEngine.on('error', (error) => console.error(`[C++ HATA] Motor baslatilamadi: ${error.message}`));
cppEngine.stdout.on('data', (data) => console.log(`[C++] ${data.toString().trim()}`));
cppEngine.stderr.on('data', (data) => console.error(`[C++ HATA] ${data.toString().trim()}`));

// 2. Node.js API ve Arayuz Sunucusunu Baslat
const nodeServerPath = path.join(__dirname, 'backend_node', 'server.js');
console.log(`[2/2] Node.js Backend Baslatiliyor... (${nodeServerPath})`);

const nodeServer = spawn('node', [nodeServerPath], { stdio: 'pipe' });
nodeServer.on('error', (error) => console.error(`[Node HATA] Backend baslatilamadi: ${error.message}`));
let browserOpened = false;
nodeServer.stdout.on('data', (data) => {
    const output = data.toString().trim();
    console.log(`[Node] ${output}`);
    
    // Sunucu hazir oldugunda tarayiciyi ac
    if (!browserOpened && output.includes('3000')) {
        browserOpened = true;
        console.log(`\n==========================================`);
        console.log(`Node API hazir; C++ yerel video motoru baglantisi suruyor.`);
        console.log(`Tarayici Arayuzu Aciliyor (http://localhost:3000)...`);
        console.log(`==========================================\n`);
        const startCmd = os.platform() === 'win32' ? 'start' : (os.platform() === 'darwin' ? 'open' : 'xdg-open');
        spawn(startCmd, ['http://localhost:3000'], { shell: true });
    }
});
nodeServer.stderr.on('data', (data) => console.error(`[Node HATA] ${data.toString().trim()}`));

// Kapanista yalnizca bu launcher'in baslattigi surecleri durdur.
const shutdown = () => {
    console.log("\nKapatiliyor...");
    cppEngine.kill();
    nodeServer.kill();
    process.exit();
};

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
