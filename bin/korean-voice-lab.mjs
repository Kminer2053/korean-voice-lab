#!/usr/bin/env node
// 내 목소리 생성기(korean-voice-lab) 설치·실행 런처. 의존성 없음(Node 18+).
//
// 파이썬 앱은 이 패키지 안에 들어 있고, `install` 때 사용자 폴더(기본 ~/.korean-voice-lab)에 펼쳐
// 그 안의 가상환경에만 설치한다. 녹음(references/)·결과(outputs/)·발음 사전·설정은 그 폴더에 남고,
// `update`(또는 새 버전으로 `install`)는 코드 파일만 바꾼다.
import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, platform, arch } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PKG_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PKG = JSON.parse(readFileSync(join(PKG_DIR, "package.json"), "utf8"));
const HOME = resolve(process.env.KOREAN_VOICE_LAB_HOME || join(homedir(), ".korean-voice-lab"));
const IS_WIN = platform() === "win32";
const IS_MAC_ARM = platform() === "darwin" && arch() === "arm64";
const VENV_PY = IS_WIN ? join(HOME, ".venv", "Scripts", "python.exe") : join(HOME, ".venv", "bin", "python");
// 패키지에서 사용자 폴더로 옮길 앱 파일(사용자 자료는 여기 없다)
const APP_FILES = (PKG.files || []).filter((f) => !f.startsWith("bin") && !f.startsWith("!") && f !== "package.json");

const say = (msg) => process.stderr.write(msg + "\n");
const die = (msg, code = 1) => { say(`\n[오류] ${msg}`); process.exit(code); };

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd: HOME, shell: false, ...opts });
  if (r.error) die(`${cmd} 실행 실패: ${r.error.message}`);
  return r.status ?? 1;
}

function findPython() {
  if (process.env.PYTHON) return [process.env.PYTHON];
  const cands = IS_WIN
    ? [["py", "-3.12"], ["py", "-3.11"], ["python"]]
    : [["python3.12"], ["/opt/homebrew/bin/python3.12"], ["python3.13"], ["/opt/homebrew/bin/python3.13"], ["python3.11"], ["python3"]];
  for (const c of cands) {
    const r = spawnSync(c[0], [...c.slice(1), "-c", "import sys;print('%d.%d'%sys.version_info[:2])"], { encoding: "utf8" });
    const v = (r.stdout || "").trim();
    const [maj, min] = v.split(".").map(Number);
    const maxMinor = IS_WIN ? 12 : 13;
    if (r.status === 0 && maj === 3 && min >= 11 && min <= maxMinor) return c;
  }
  return null;
}

function syncApp() {
  mkdirSync(HOME, { recursive: true });
  for (const f of APP_FILES) {
    const src = join(PKG_DIR, f);
    if (existsSync(src)) cpSync(src, join(HOME, f), { recursive: true, force: true });
  }
  writeFileSync(join(HOME, ".installed-version"), PKG.version + "\n");
  say(`앱 파일: ${HOME} (v${PKG.version})`);
}

function install(args) {
  syncApp();
  const withQwen = args.includes("--with-qwen");
  if (IS_WIN) {
    // setup.bat 이 서버·Chatterbox(·Qwen3) 가상환경과 CUDA/CPU PyTorch 를 고른다. CI=1 이면 멈추지 않는다.
    const code = run("cmd.exe", ["/d", "/c", "setup.bat"], {
      env: { ...process.env, CI: "1", VOICELAB_WITH_QWEN: withQwen ? "y" : "n" },
    });
    if (code !== 0) die("setup.bat 이 실패했습니다. 위의 메시지를 확인하세요.");
  } else {
    const py = findPython();
    if (!py) die(IS_MAC_ARM ? "Python 3.11–3.13 을 찾지 못했습니다. brew install python@3.12 후 다시 실행하세요."
                            : "Python 3.11–3.13 을 찾지 못했습니다. 설치한 뒤 다시 실행하거나 PYTHON 환경변수로 지정하세요.");
    if (!existsSync(VENV_PY) && run(py[0], [...py.slice(1), "-m", "venv", ".venv"]) !== 0) die("가상환경을 만들지 못했습니다.");
    run(VENV_PY, ["-m", "pip", "install", "--upgrade", "pip"]);
    if (IS_MAC_ARM) {
      // 맥: 서버 + MLX 엔진(Qwen3·Chatterbox)이 한 가상환경에
      if (run(VENV_PY, ["-m", "pip", "install", "-r", "requirements.txt"]) !== 0) die("패키지 설치에 실패했습니다.");
    } else {
      // 리눅스(와 인텔 맥): 서버 가상환경 + Chatterbox PyTorch 가상환경
      if (run(VENV_PY, ["-m", "pip", "install", "-r", join("requirements", "server.txt")]) !== 0) die("서버 패키지 설치에 실패했습니다.");
      const gpu = spawnSync("nvidia-smi", [], { stdio: "ignore" }).status === 0;
      const index = gpu ? "https://download.pytorch.org/whl/cu124" : "https://download.pytorch.org/whl/cpu";
      say(`PyTorch: ${gpu ? "CUDA 12.4" : "CPU"}`);
      const engines = [["chatterbox", ["requirements/engine-chatterbox.txt"], "requirements/engine-chatterbox-src.txt"]];
      if (withQwen) engines.push(["qwen3", ["requirements/engine-qwen3.txt"], null]);
      for (const [name, reqs, src] of engines) {
        const ev = join(HOME, `.venv-${name}`, "bin", "python");
        if (!existsSync(ev) && run(py[0], [...py.slice(1), "-m", "venv", `.venv-${name}`]) !== 0) die(`${name} 가상환경을 만들지 못했습니다.`);
        run(ev, ["-m", "pip", "install", "--upgrade", "pip"]);
        if (run(ev, ["-m", "pip", "install", "torch==2.6.0", "torchaudio==2.6.0", "--index-url", index]) !== 0) die("PyTorch 설치에 실패했습니다.");
        for (const r of reqs) if (run(ev, ["-m", "pip", "install", "-r", r]) !== 0) die(`${name} 엔진 설치에 실패했습니다.`);
        if (src && run(ev, ["-m", "pip", "install", "--no-deps", "-r", src]) !== 0) die(`${name} 엔진 본체 설치에 실패했습니다.`);
      }
    }
  }
  say("\n설치가 끝났습니다. 화면: npx korean-voice-lab start   ·   에이전트: npx korean-voice-lab mcp");
  say("모델 가중치는 첫 생성 때 내려받습니다(2.5–3GB).");
}

function ensureInstalled() {
  if (!existsSync(VENV_PY)) die(`아직 설치하지 않았습니다. 먼저 실행하세요: npx korean-voice-lab install\n(설치 위치: ${HOME})`);
  const installed = existsSync(join(HOME, ".installed-version")) ? readFileSync(join(HOME, ".installed-version"), "utf8").trim() : "";
  if (installed && installed !== PKG.version) say(`알림: 설치된 앱은 v${installed}, 이 런처는 v${PKG.version} 입니다. 맞추려면 npx korean-voice-lab update`);
}

// cwd: 명령줄은 사용자가 있는 폴더(상대 경로 입력·출력이 거기 기준), 서버·MCP 는 설치 폴더
function passthrough(script, args, cwd = HOME) {
  ensureInstalled();
  const child = spawn(VENV_PY, [join(HOME, script), ...args], { stdio: "inherit", cwd });
  const stop = (sig) => () => child.kill(sig);
  process.on("SIGINT", stop("SIGINT"));
  process.on("SIGTERM", stop("SIGTERM"));
  child.on("exit", (code, sig) => process.exit(sig ? 1 : code ?? 0));
}

function doctor() {
  say(`런처 v${PKG.version} · Node ${process.version} · ${platform()} ${arch()}`);
  say(`설치 위치: ${HOME} ${existsSync(HOME) ? "" : "(없음)"}`);
  const py = findPython();
  say(`Python: ${py ? py.join(" ") : "찾지 못함(3.11–3.13 필요)"}`);
  say(`가상환경: ${existsSync(VENV_PY) ? "있음" : "없음 — npx korean-voice-lab install"}`);
  if (existsSync(VENV_PY)) run(VENV_PY, ["voicelab_cli.py", "engines"]);
}

const HELP = `내 목소리 생성기 (korean-voice-lab) v${PKG.version}

사용법: npx korean-voice-lab <명령>

  install [--with-qwen]   ${"~/.korean-voice-lab"} 에 앱을 펼치고 가상환경에 설치
                          (맥: Qwen3·Chatterbox MLX / 윈도우·리눅스: Chatterbox, --with-qwen 이면 Qwen3도)
  update                  새 버전의 코드로 바꾸고 의존성을 맞춤(녹음·결과는 그대로)
  start [--port 7860]     화면과 HTTP API 서버를 켜고 브라우저를 엶(127.0.0.1 전용)
  mcp                     MCP 서버(stdio). 예: claude mcp add voicelab -- npx -y korean-voice-lab mcp
  cli <인자…>              명령줄(voicelab_cli.py). 예: npx korean-voice-lab cli say "안녕하세요" -s talk -o hi.wav
  doctor                  설치 상태·Python·엔진 점검
  home                    설치 폴더 경로(녹음·결과가 여기 있음)

설치 위치는 KOREAN_VOICE_LAB_HOME 환경변수로 바꿀 수 있습니다.
자세한 안내: ${PKG.homepage}`;

const [cmd, ...rest] = process.argv.slice(2);
switch (cmd) {
  case "install": case "setup": install(rest); break;
  case "update": install(rest); break;
  case "start": passthrough("app.py", rest.includes("--no-open") ? rest.filter((a) => a !== "--no-open") : ["--open", ...rest]); break;
  case "mcp": passthrough("mcp_server.py", rest); break;
  case "cli": passthrough("voicelab_cli.py", rest, process.cwd()); break;
  case "doctor": doctor(); break;
  case "home": console.log(HOME); break;
  case "-v": case "--version": console.log(PKG.version); break;
  default: console.log(HELP); process.exit(cmd && cmd !== "help" && cmd !== "-h" && cmd !== "--help" ? 1 : 0);
}
