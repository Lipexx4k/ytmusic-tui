# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.
O formato segue livremente o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto usa [versionamento semântico](https://semver.org/lang/pt-BR/).

## [0.1.0] - 2026-10-15

Primeira versão publicada. 🎉

### Adicionado

- Busca de músicas e álbuns (duas requisições em paralelo, ~2s)
- Reprodução via mpv (libmpv) com qualidade selecionável e fila contínua
- Aba 💿 Álbum: faixas, artista, ano e download do álbum inteiro (`A`), pulando
  as faixas já baixadas
- Downloads via yt-dlp + ffmpeg (MP3/Opus/M4A/FLAC, tags ID3 e capa embutida),
  com progresso em tempo real e concorrência configurável
- Biblioteca local em SQLite (faixas baixadas e curtidas locais)
- Configuração por TOML e variáveis de ambiente (`YTMUSIC_*`), editável na aba
  ⚙️ Config do app
- 52 testes automatizados (offline, com mocks) + testes de integração opcionais
  (`YTMUSIC_INTEGRATION=1`)
- CI no GitHub Actions (ruff + testes em Python 3.11 e 3.13)

### Corrigido

- Downloads duplicados: o mesmo vídeo não é mais enfileirado duas vezes
  enquanto está em andamento (dois downloads disputariam o mesmo arquivo)
- Primeiro contato sem o mpv instalado agora mostra uma mensagem clara em vez
  de um traceback do python-mpv

### Limitações conhecidas

- Opera sem conta Google (o OAuth do ytmusicapi foi descontinuado em 2025);
  curtidas e biblioteca são locais
- ~80% do código foi produzido em "vibe coding" com IA (ver README)
