# YouTube Music TUI

Cliente terminal minimalista e rápido para YouTube Music, escrito em Python com Textual.

## Características

- 🎵 **Reprodução de música** via mpv (streaming direto, alta qualidade)
- 🔍 **Busca** de músicas e álbuns (com tipo e ano indicados nos resultados)
- 💿 **Aba de álbum** com faixas, artista e download do álbum inteiro (`a`)
- 📚 **Biblioteca local** SQLite (músicas curtidas, histórico, playlists)
- 📥 **Download** de músicas e álbuns para ouvir offline (yt-dlp + ffmpeg)
- 🚫 **Sem login necessário** - busca, reprodução e download funcionam anonimamente
- ⌨️ **Interface TUI** responsiva e minimalista (Textual)
- ⚡ **Rápido e leve** - alternativa ao player web pesado

## Requisitos

- Python 3.11+
- mpv (player de áudio)
- ffmpeg (para conversão de áudio nos downloads)

## Instalação

### 1. Dependências do sistema

```bash
# Ubuntu/Debian
sudo apt install mpv ffmpeg python3.11-venv

# Arch Linux
sudo pacman -S mpv ffmpeg python

# Fedora
sudo dnf install mpv ffmpeg python3.11

# macOS (Homebrew)
brew install mpv ffmpeg python@3.11
```

### 2. Instalar o pacote

```bash
git clone https://github.com/seu-usuario/ytmusic-tui
cd ytmusic-tui
pip install -e .[dev]  # ou apenas: pip install -e .
```

### 3. Configurar (opcional)

O app funciona sem nenhuma configuração. Para ajustar player, downloads e
interface, copie o arquivo de exemplo:

```bash
cp config.example.toml ~/.config/ytmusic-tui/config.toml
# Edite conforme suas preferências
```

> **Sobre login (OAuth):** o `ytmusicapi` (API embutida) perdeu a autenticação
> OAuth em agosto de 2025 — o Google passou a rejeitar tokens OAuth nos
> endpoints internos do YouTube Music com `HTTP 400` (issue aberta:
> [sigma67/ytmusicapi#813](https://github.com/sigma67/ytmusicapi/issues/813)).
> Por isso o `ytmusic-tui` opera **sem conta**: busca, reprodução e download
> funcionam anonimamente, e a biblioteca é local (SQLite).
>
> **Reprodução:** o mpv usa o `yt-dlp` instalado junto com o app (via hook
> `ytdl_hook-ytdl_path`) — e não o youtube-dl embutido e desatualizado — para
> decodificar os streams do YouTube Music. O libmpv também exige `LC_NUMERIC`
> em `"C"`, o que o app restaura antes de iniciar (o `ytmusicapi` muda o
> locale para `en_US.UTF-8`, o que fazia o mpv abortar).

## Configuração

Arquivo: `~/.config/ytmusic-tui/config.toml`

```toml
# Player
mpv_volume = 50
mpv_audio_quality = "high"  # low, medium, high, best

# Downloads
download_dir = "~/Music/YouTube Music"
download_format = "mp3"  # mp3, opus, m4a, flac
download_quality = "320"  # kbps para mp3
download_concurrent = 3
embed_metadata = true

# Interface
show_notifications = true
auto_play_next = true
```

As alterações feitas na aba **Config** do app são aplicadas na hora e gravadas
nesse mesmo arquivo (as chaves existentes são preservadas).

## Uso

```bash
# Executar
ytmusic-tui

# Ou diretamente
python main.py
```

### Atalhos de teclado

| Tecla | Ação |
|-------|------|
| `Ctrl+Q` | Sair |
| `Ctrl+S` | Focar busca |
| `Enter` | Tocar faixa selecionada / abrir álbum selecionado |
| `Espaço` | Play/Pause |
| `→` / `←` | Próxima/Anterior |
| `Ctrl+D` | Baixar música atual |
| `A` | Baixar o álbum inteiro aberto na aba 💿 Álbum |
| `Esc` | Voltar do álbum para a busca |
| `L` | Curtir/Descurtir |
| `Ctrl+L` | Ir para Biblioteca |
| `F1` | Ajuda |

Na busca, músicas e álbuns aparecem em seções separadas — cada álbum mostra
o tipo e o ano (ex.: `💿 Parachutes — Coldplay  (Album, 2000)`). `Enter` num
álbum abre a aba **💿 Álbum** com as faixas e o nome do artista; ali `Enter`
toca uma faixa (a fila continua com o resto do álbum) e `a` (ou o botão
**⬇ Baixar álbum inteiro**) enfileira o download de todas as faixas,
pulando as que já estão baixadas.

Ao terminar uma faixa, a próxima da lista tocada continua automaticamente
(`auto_play_next`). Downloads concluídos entram na aba **Biblioteca** e podem
ser reproduzidos do arquivo local.

## Estrutura do Projeto

```
ytmusic-tui/
├── main.py                 # Entry point
├── pyproject.toml          # Configuração do projeto
├── config.example.toml     # Exemplo de configuração
├── src/
│   └── ytmusic_tui/
│       ├── __init__.py
│       ├── config/         # Configurações (pydantic-settings, persistência TOML)
│       ├── api/            # Wrapper ytmusicapi (modo anônimo)
│       ├── player/         # Player mpv (libmpv/python-mpv)
│       ├── download/       # Downloads yt-dlp
│       ├── library/        # Biblioteca local (SQLAlchemy)
│       └── tui/            # Interface Textual
└── tests/
```

## Desenvolvimento

```bash
# Instalar dependências de dev
pip install -e .[dev]

# Formatador
ruff format .

# Linter
ruff check .

# Type checking
mypy src/

# Testes
pytest
```

## Roadmap

- [ ] Sincronização de playlists com YouTube Music
- [ ] Radio/Mix automático
- [ ] Letras sincronizadas
- [ ] Equalizador
- [ ] Temas personalizados
- [ ] Integração com Last.fm / ListenBrainz
- [ ] Controle via MPRIS (integração desktop)

## Licença

MIT License - veja [LICENSE](LICENSE) para detalhes.

## Agradecimentos

- [ytmusicapi](https://github.com/sigma67/ytmusicapi) - API não oficial do YouTube Music
- [Textual](https://github.com/Textualize/textual) - Framework TUI
- [mpv](https://mpv.io/) - Player de mídia
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Downloader de vídeo/áudio