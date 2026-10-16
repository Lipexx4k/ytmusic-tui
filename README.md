# 🎧 YouTube Music TUI

Cliente **TUI minimalista e rápido** para YouTube Music, direto no terminal: busca, reprodução (mpv), download de músicas e álbuns (yt-dlp + ffmpeg) e biblioteca local — **sem precisar de conta do Google**.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-337%20passando-brightgreen)
![CI](https://github.com/Lipexx4k/ytmusic-tui/actions/workflows/ci.yml/badge.svg)
![Vibe-coded](https://img.shields.io/badge/vibe--coded-~80%25-ff69b4)

> ## ⚠️ Aviso de honestidade: este projeto é ~80% "vibe-coded"
>
> A maior parte deste código foi escrita em **vibe coding** — conversando com um assistente de IA, com revisão, ajustes e testes manuais do autor no meio do caminho. São **337 testes automatizados** e uso real no dia a dia, então **funciona de verdade** — mas espere arestas: bugs ocasionais, código "com cara de IA" aqui e ali e funcionalidades faltando (veja **Limitações**).
> Achou um bug? Abra uma [issue](https://github.com/Lipexx4k/ytmusic-tui/issues). PRs são muito bem-vindos! 💜

---

## ✨ Características

- 🎵 **Reprodução de música** via mpv (streaming direto, qualidade selecionável)
- 🔍 **Busca** de músicas (25) e álbuns (15) em paralelo, com tipo e ano nos álbuns (`💿 My Dear Melancholy, — The Weeknd  (EP, 2018)`)
- 💿 **Aba de álbum**: abra um álbum da busca e veja faixas, artista e ano — `Enter` toca (com fila contínua) e `A` baixa o álbum inteiro, **pulando faixas já baixadas**
- 📥 **Download** via yt-dlp + ffmpeg: melhor stream disponível → MP3 320 kbps (ou opus/m4a/flac), com tags ID3 e **capa embutida**
- 📚 **Biblioteca local** em SQLite (nada de nuvem): faixas baixadas, curtidas locais e reprodução do arquivo local
- 📊 Aba de **Downloads** com progresso em tempo real e downloads simultâneos configuráveis
- 🚫 **Sem login**: busca, reprodução e download operam anonimamente
- ⌨️ Interface **Textual** responsiva, com mouse (abas, listas, botões) e atalhos estilo vim
- ⚡ **Leve**: sem Electron, sem navegador — só Python + mpv

## 📸 Screenshots

### Busca — músicas e álbuns em seções separadas

```text
 ⭘                                      YouTube Music TUI                                  04:43:20
  🏠 Início    🔍 Busca    📚 Biblioteca    📥 Downloads    ⚙️ Config
━━━━━━━━━━━━━━╸━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
 │  my dear melancholy                                                                            │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘

 ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                                │
 │  🎵 Músicas                                                                                    │
 │ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
 │ │ I Was Never There — The Weeknd, Gesaffelstein  (4:02)                                      │ │
 │ │ Try Me — The Weeknd  (3:42)                                                                │ │
 │ │ my dear melancholy — msht  (2:16)                                                          │ │
 │ │ Wasted Times — The Weeknd  (3:41)                                                        ▆▆│ │
 │ │ Hurt You — The Weeknd, Gesaffelstein  (3:51)                                               │ │
 │ │ TMJ (Acoustic Version) — MOHXSIN  (2:22)                                                   │ │
 │ │ Privilege — The Weeknd  (2:51)                                                             │ │
 │ │ my dear melancholy (slowed) — msht  (2:33)                                                 │ │
 │ │ Rockstar without guitar (Remix) — MOHXSIN  (3:10)                                          │ │
 │ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
 │  💿 Álbuns                                                                                     │
 │ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
 │ │ 💿 My Dear Melancholy, — The Weeknd  (EP, 2018)                                            │ │
 │ │ 💿 my dear melancholy — msht  (EP, 2026)                                                   │ │
 │ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
 │                                                                                                │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────────────────────────────────────
                                             ┌───┐ ┌───┐ ┌───┐            0:00   ━━━━━━━━━━━━━━━━━
                                             │ ⏮ │ │ ⏯ │ │ ⏭ │
                                             └───┘ └───┘ └───┘
```

### Aba de álbum — `Enter` na busca abre aqui; `A` baixa o álbum inteiro

```text
 ⭘                                      YouTube Music TUI                                  04:43:21
  🏠 Início    🔍 Busca    💿 My Dear Melancholy    📚 Biblioteca    📥 Downloads    ⚙️ Config
━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 💿 My Dear Melancholy, — The Weeknd · 2018 · 6 faixas

 ┌────────────────────────────┐
 │ ⬇ Baixar álbum inteiro (a) │
 └────────────────────────────┘

 ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ Call Out My Name — The Weeknd  (3:49)                                                          │
 │ Try Me — The Weeknd  (3:42)                                                                    │
 │ Wasted Times — The Weeknd  (3:41)                                                              │
 │ I Was Never There — The Weeknd, Gesaffelstein  (4:02)                                          │
 │ Hurt You — The Weeknd, Gesaffelstein  (3:51)                                                   │
 │ Privilege — The Weeknd  (2:51)                                                                 │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 │                                                                                                │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────────────────────────────────────
                                             ┌───┐ ┌───┐ ┌───┐            0:00   ━━━━━━━━━━╺━━━━━━
                                             │ ⏮ │ │ ⏯ │ │ ⏭ │
                                             └───┘ └───┘ └───┘
```

*(Capturas do app real, com dados ao vivo da API; as cores variam conforme o tema do seu terminal.)*

## 📋 Requisitos

- **Python 3.11+**
- **mpv** (com libmpv) — é o player. Na maioria das distros o pacote `mpv` já inclui a libmpv (se o app não abrir, veja *Problemas comuns na instalação*)
- **ffmpeg** — conversão e marcação dos downloads
- Dependências Python (ytmusicapi, textual, yt-dlp, sqlalchemy…) são instaladas via pip/pipx junto com o app
- Terminal com cores (256/true color) e Unicode — **mínimo 80×24**, recomendado 100×30+

## 🖥️ Compatibilidade

| Plataforma | Status |
|------------|--------|
| **Linux** | ✅ **Testado** — desenvolvido e usado no LMDE 7 (base Debian 13). Qualquer distro com Python 3.11+ e mpv deve funcionar |
| **macOS** | 🟡 Não testado — deve funcionar com `brew install mpv ffmpeg` |
| **Windows (WSL2)** | 🟡 Não testado — funciona dentro do WSL seguindo as instruções de Linux |
| **Windows (nativo)** | ❌ Não suportado oficialmente — exigiria configurar a DLL da libmpv manualmente |

## ✅ Versões conhecidas boas

Combinações validadas (o conjunto exato de dependências Python usado no CI está no [`uv.lock`](uv.lock); os pisos, no `pyproject.toml`):

| Componente | Versão validada | Como conferir |
|---|---|---|
| **Python** | 3.11–3.13 (CI roda em 3.11 e 3.13; desenvolvimento do autor em 3.13.5) | `python3 --version` |
| **mpv / libmpv** | mpv 0.40.0 com libmpv.so.2 (LMDE 7 / Debian 13) | `mpv --version \| head -n1` · `ldconfig -p \| grep libmpv` |
| **ffmpeg** | 7.1.5 (Debian 13) | `ffmpeg -version \| head -n1` |
| **yt-dlp** | piso `>=2024.1.0` no pyproject; 2026.8.19 no ambiente do autor | `yt-dlp --version` · no venv: `python -c "import yt_dlp; print(yt_dlp.version.__version__)"` |

O **yt-dlp** muda com frequência (o YouTube muda as regras do jogo): mantenha-o atualizado — o Dependabot já abre PR semanal e uma atualização que quebre a reprodução aparece no CI antes do merge.

## 📦 Instalação

### 1. Dependências do sistema

```bash
# Ubuntu / Debian / Linux Mint / LMDE
sudo apt install mpv ffmpeg python3-venv

# Arch / Manjaro / EndeavourOS
sudo pacman -S mpv ffmpeg python

# Fedora
sudo dnf install mpv ffmpeg python3

# openSUSE
sudo zypper install mpv ffmpeg python3

# macOS (Homebrew)
brew install mpv ffmpeg python
```

### 2. Instalar o app

**Opção A — pipx (recomendada, ambiente isolado):**

```bash
pipx install git+https://github.com/Lipexx4k/ytmusic-tui
```

**Opção B — pip:**

```bash
pip install --user git+https://github.com/Lipexx4k/ytmusic-tui
```

**Opção C — do código-fonte (para desenvolver):**

```bash
git clone https://github.com/Lipexx4k/ytmusic-tui
cd ytmusic-tui
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/ytmusic-tui    # ou: .venv/bin/python main.py
```

### 3. Configuração (opcional)

O app **funciona sem nenhuma configuração**. Se quiser ajustar player, downloads e interface:

```bash
mkdir -p ~/.config/ytmusic-tui
cp config.example.toml ~/.config/ytmusic-tui/config.toml
```

### Problemas comuns na instalação

- **`Cannot find libmpv in the usual places`** (ou mensagem parecida do python-mpv) ao abrir o app: o Python não encontrou a libmpv. No Ubuntu/Debian instale também `sudo apt install libmpv-dev` — ele fornece o link `libmpv.so` que o Python procura (no Ubuntu 24.04, por exemplo, o pacote `mpv` sozinho nem sempre basta).
- **A música não toca / o stream falha**: quase sempre é o yt-dlp desatualizado em relação a alguma mudança do YouTube — atualize o app e o yt-dlp no mesmo ambiente de instalação (`pip install -U yt-dlp` no venv, ou `pipx upgrade` + `pipx runpip ytmusic-tui install -U yt-dlp`).

## 🚀 Uso

```bash
ytmusic-tui              # instalado via pip/pipx
python -m ytmusic_tui    # como módulo
python main.py           # direto do código-fonte (usa src/, sem instalar o pacote)
```

### Fluxo básico

1. `Ctrl+S` para ir à busca → digite e `Enter`
2. `Enter` numa música toca; `→` / `←` navegam pela fila
3. `Enter` num álbum abre a aba 💿 com as faixas; `A` (ou o botão) baixa o álbum inteiro
4. `Ctrl+D` baixa a música em reprodução — acompanhe na aba 📥 Downloads
5. `Ctrl+L` abre a biblioteca local: toque direto dos arquivos baixados

### Atalhos de teclado

| Tecla | Ação |
|-------|------|
| `Ctrl+S` | Ir para a busca |
| `Enter` | Tocar faixa / abrir álbum selecionado |
| `Espaço` | Play/Pause |
| `→` / `←` | Próxima / anterior |
| `Ctrl+D` | Baixar a faixa em reprodução |
| `A` | Baixar o álbum inteiro (aba do álbum) |
| `Esc` | Voltar do álbum para a busca |
| `L` | Curtir / descurtir (local, para faixas baixadas) |
| `Ctrl+L` | Ir para a biblioteca |
| `F1` | Ajuda |
| `Ctrl+Q` | Sair |

O mouse também funciona: clique nas abas, nos resultados e nos botões.

## ⚙️ Configuração

Arquivo: `~/.config/ytmusic-tui/config.toml` (todas as chaves são opcionais).
A aba **Config** do app edita as principais opções e grava nesse mesmo arquivo na hora.

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `mpv_volume` | `50` | Volume inicial (0–100) |
| `mpv_audio_quality` | `"high"` | Stream usado pelo mpv: `low`, `medium`, `high`, `best` |
| `download_dir` | `"~/Music/YouTube Music"` | Diretório dos downloads |
| `download_format` | `"mp3"` | Formato: `mp3`, `opus`, `m4a` ou `flac` |
| `download_quality` | `"320"` | Bitrate em kbps (mp3/opus) ou `"best"` |
| `download_concurrent` | `3` | Downloads simultâneos (1–10) |
| `embed_metadata` | `true` | Tags ID3 + capa embutida nos arquivos |
| `show_notifications` | `true` | Notificações toast |
| `auto_play_next` | `true` | Tocar a próxima da fila automaticamente |
| `library_db_name` | `"library.db"` | Nome do arquivo SQLite da biblioteca |
| `config_dir`, `data_dir`, `cache_dir` | XDG | Diretórios internos (avançado, geralmente não mexa) |

Variáveis de ambiente com prefixo `YTMUSIC_` têm prioridade sobre o TOML (útil para testar isolado):

```bash
YTMUSIC_DOWNLOAD_DIR=/tmp/teste YTMUSIC_DATA_DIR=/tmp/teste ytmusic-tui
```

### Onde ficam os arquivos (Linux)

| O quê | Caminho |
|-------|---------|
| Configuração | `~/.config/ytmusic-tui/config.toml` |
| Biblioteca (SQLite) | `~/.local/share/ytmusic-tui/library.db` |
| Cache | `~/.cache/ytmusic-tui/` |
| Downloads | `~/Music/YouTube Music/` |
| Log | `~/.local/state/ytmusic-tui/log/ytmusic-tui.log` |

*(Em macOS/Windows são usados os caminhos equivalentes do `platformdirs`.)*

Erros internos (por exemplo, falha ao acessar o banco da biblioteca) aparecem
na própria interface **e** são registrados no log acima — útil para investigar
ou anexar a uma issue.

## 🔧 Como funciona (por dentro)

- **[ytmusicapi](https://github.com/sigma67/ytmusicapi)** (não oficial) em **modo anônimo** para busca e metadados — a busca dispara pedidos em paralelo e leva ~2s
- **[mpv](https://mpv.io/)** (via libmpv/python-mpv) toca os streams; o mpv usa o **yt-dlp instalado junto com o app** como extrator (`ytdl_hook-ytdl_path`), então a reprodução acompanha o yt-dlp atualizado em vez do extrator embutido e velho do mpv
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp) + ffmpeg** baixam o melhor stream de áudio e convertem para o formato configurado, com capa e tags
- **SQLAlchemy + SQLite** guardam a biblioteca local (faixas baixadas, curtidas)

> **Por que sem login?** O Google desativou a autenticação OAuth do ytmusicapi em 2025 — os tokens passaram a ser rejeitados com HTTP 400 ([sigma67/ytmusicapi#813](https://github.com/sigma67/ytmusicapi/issues/813)). Como busca, reprodução e download funcionam anonimamente, este cliente escolheu operar **sem conta**: nada de sincronização, tudo local.
>
> ⚙️ Detalhe técnico: o libmpv exige `LC_NUMERIC=C`, mas o ytmusicapi muda o locale para `en_US.UTF-8` (e o mpv abortava por isso). O app restaura o locale antes de iniciar o player.

## ⚠️ Limitações

**Conta e biblioteca:**
- Sem login: curtidas, playlists e recomendações **da sua conta** não aparecem; a "curtida" (`L`) é **local** e só funciona para faixas já baixadas
- Não há sincronização com o YouTube Music — a biblioteca vive só no seu `library.db`

**Busca e catálogo:**
- Até **25 músicas + 15 álbuns** por consulta
- Sem filtros avançados (busca por artista, playlist, ordenação etc.)
- Playlists ainda não são suportadas (veja o Roadmap)

**Downloads e qualidade:**
- A qualidade real depende da fonte: o YouTube Music serve tipicamente áudio de **~128–256 kbps** (AAC/Opus); o "MP3 320" é uma conversão — não inventa qualidade, mas padroniza os arquivos
- O download depende do yt-dlp; quando o YouTube muda algo, atualizar o yt-dlp no mesmo ambiente (ou reinstalar/atualizar o app) costuma resolver

**Projeto jovem:**
- Interface e mensagens **em português**
- **~80% vibe-coded** (aviso no topo 🙂): os 337 testes cobrem o fluxo principal, mas bugs ocasionais são esperados
- Sem MPRIS, letras, equalizador, rádio automático e temas (Roadmap)

## 🗂️ Estrutura do projeto

```text
ytmusic-tui/
├── main.py                    # Atalho para rodar do código-fonte (usa src/ direto)
├── pyproject.toml             # Metadados e dependências (pip/pipx)
├── config.example.toml        # Modelo de configuração comentado
├── src/ytmusic_tui/
│   ├── main.py                # Entry point do console script `ytmusic-tui`
│   ├── config/                # Configuração (pydantic-settings + persistência TOML)
│   ├── api/                   # ytmusicapi anônimo (busca, álbuns)
│   ├── player/                # Player mpv (libmpv) + integração com yt-dlp
│   ├── download/              # Fila de downloads yt-dlp (progresso, concorrência)
│   ├── library/               # Biblioteca SQLite (SQLAlchemy)
│   ├── log.py                 # Logging em arquivo (com rotação)
│   └── tui/                   # Interface Textual
│       ├── app.py             # Ciclo de vida do app + main() (app.tcss ao lado)
│       ├── screens.py         # MainScreen: abas, atalhos e navegação
│       ├── widgets.py         # Widgets personalizados (listas, barra do player)
│       └── *_controller.py    # Reprodução, downloads e biblioteca (mixins)
└── tests/                     # 337 testes em camadas (L1 mocks + L2 local) + integração opt-in
```

## 🛠️ Desenvolvimento

```bash
git clone https://github.com/Lipexx4k/ytmusic-tui
cd ytmusic-tui
uv sync --locked --extra dev    # cria/atualiza o .venv a partir do uv.lock

# Testes (offline, tudo com mocks — L1 + L2)
.venv/bin/python -m pytest tests/ -q

# Cobertura de branches de download/biblioteca/player (informativa, sem threshold)
.venv/bin/python -m pytest tests/ -q \
  --cov=ytmusic_tui.download --cov=ytmusic_tui.library --cov=ytmusic_tui.player \
  --cov-branch --cov-report=term

# Lint
.venv/bin/ruff check src/ tests/

# Formatação
.venv/bin/ruff format src/ tests/

# Testes de integração (falam com o YouTube Music de verdade; desabilitados por padrão)
YTMUSIC_INTEGRATION=1 .venv/bin/python -m pytest tests/test_integration.py -v

# Auditoria de vulnerabilidades do conjunto travado (o mesmo que o CI audita)
uv export --frozen --no-emit-project --extra dev --no-hashes -o /tmp/ytm-locked.txt
.venv/bin/pip-audit -r /tmp/ytm-locked.txt
```

O **[uv](https://docs.astral.sh/uv/)** é a ferramenta de desenvolvimento/CI: o `uv.lock` fixa as versões exatas de runtime + dev e o CI instala dele (`uv sync --locked`). Se `pyproject.toml` e `uv.lock` divergirem, o `--locked` falha de propósito — depois de editar dependências, rode `uv lock`. Sem uv? `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` continua funcionando (sem o lockfile — é o CI que o usa).

Os testes cobrem TUI (via `run_test` do Textual), API, player, downloads e biblioteca, em duas camadas offline: **L1** (unit/comportamento, com mocks finos) e **L2** (`tests/integration_local/` — integração local com worker, reserva/temporários e banco de verdade, e falsos "de verdade": yt-dlp stubado no import tardio e um ffmpeg **executável** no PATH). **Nenhum teste da suíte padrão toca a rede nem o player de verdade** — a L2 bloqueia `socket` de propósito, então qualquer conexão falha na hora com mensagem clara; a cobertura de branches (comando acima) é informativa, sem threshold; os testes de integração reais são opt-in (comando acima) e servem para detectar quando o YouTube Music mudar algo.

O **CI (GitHub Actions)** roda `ruff` + a suíte offline em Python 3.11 e 3.13 a cada push, **instalando do `uv.lock`** (`uv sync --locked` — o job falha se o lock estiver ausente ou fora de sincronia com o `pyproject.toml`), um job de segurança que exporta o conjunto travado e roda `pip-audit` (falha em vulnerabilidade conhecida) e um job de pacote que confere o conteúdo do wheel/sdist e instala o wheel num ambiente limpo. A cobertura de branches (download, biblioteca e player) roda no job de testes como passo **informativo** — sem threshold e sem bloquear o CI —, numa perna só (Python 3.13).

As dependências são atualizadas pelo **Dependabot** (PRs semanais, grupos dev/runtime — com o lockfile, ele atualiza `uv.lock` e `pyproject.toml` juntos): o CI roda em cada PR, então uma atualização que quebre o app fica visível ali antes de entrar — útil num projeto que depende de serviços externos que mudam com frequência (YouTube, mpv, yt-dlp).

### Releases e atualizações

Cada release corresponde a um **commit rastreável** com versão no `pyproject.toml` e entrada no `CHANGELOG.md`, tag anotada (`vX.Y.Z`) e **CI verde no commit** (ex.: `v0.1.2` → commit `84b6d80`). As releases são **manuais** — nada é publicado automaticamente; hashes (SHA-256) dos artefatos e a automação do processo entram numa etapa futura.

Atualizações de dependência seguem um caminho único: **Dependabot abre o PR → CI obrigatório (3.11/3.13 + lockfile + pip-audit + pacote) → merge manual**. Merge não é release: nenhuma atualização vai direto para uma release estável.

## 🗺️ Roadmap

- [ ] Playlists locais
- [ ] Rádio/Mix automático (autoplay infinito)
- [ ] Letras sincronizadas
- [ ] Controle via MPRIS (integ. com o desktop)
- [ ] Equalizador
- [ ] Temas personalizados
- [ ] Integração com Last.fm / ListenBrainz

## 📄 Licença

MIT — veja [LICENSE](LICENSE) para detalhes. © 2026 Eeyore.

## 💜 Agradecimentos

- [ytmusicapi](https://github.com/sigma67/ytmusicapi) — API não oficial do YouTube Music
- [Textual](https://github.com/Textualize/textual) — framework TUI
- [mpv](https://mpv.io/) — player de mídia
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — download de áudio
- [ffmpeg](https://ffmpeg.org/) — conversão e metadados
- [Rich](https://github.com/Textualize/rich), [SQLAlchemy](https://www.sqlalchemy.org/) e [pydantic](https://docs.pydantic.dev/) — o resto da base
