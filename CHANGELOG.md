# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.
O formato segue livremente o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto usa [versionamento semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Alterado

- Downloads usam uma máquina de estados explícita (T02): novos estados
  "validando" e "interrompido"; cancelar não afeta as outras tarefas e nunca
  sobrescreve um resultado já finalizado; encerrar o app marca downloads em
  voo como interrompidos (a retomada completa chega com T04)
- Faixas diferentes que gerariam o mesmo arquivo final não são mais
  enfileiradas em paralelo (evita disputa pelo mesmo caminho de saída)

## [0.1.2] - 2026-10-15

### Adicionado

- Auditoria de vulnerabilidades conhecidas (`pip-audit`) nas dependências:
  no CI e nas ferramentas de desenvolvimento
- Dependabot também para as GitHub Actions do CI (com `checkout` e
  `setup-python` atualizados para a v7, sem os avisos de depreciação do Node)
- Gates de formatação (`ruff format --check`) e tipagem (`mypy`) no CI, além
  de um job que constrói o pacote (sdist + wheel) e testa a instalação dele
  em ambiente limpo (import do app + console script)
- Teste que garante que `__version__` e o `version` do pyproject não divergem

### Alterado

- `ruff format` aplicado em todo o `src/` e `tests/` (sem mudança de
  comportamento)
- Tipagem: os 116 erros do `mypy` foram zerados — anotações completas nos
  módulos, `Base` declarativa no estilo SQLAlchemy 2.0 e overrides
  documentados para as bibliotecas sem stubs (`mpv`, `yt_dlp`) e para a
  dívida conhecida de `Column[...]` em `library.service`
- Metadados de licença no formato SPDX (`license = "MIT"` + `license-files`),
  eliminando os avisos de depreciação do setuptools (prazo: fev/2027)

### Corrigido

- Selo de testes no README (e as demais menções): dizia 55, mas a suíte tem
  62 testes passando (valor conferido com `pytest` em ambiente limpo, como
  manda o manual)
- Nomes de arquivo com muitos caracteres multibyte (acentos, CJK, emoji)
  agora são cortados também por bytes (limite de 255 bytes por componente do
  filesystem), evitando falha do download por nome longo

## [0.1.1] - 2026-10-15

### Adicionado

- Logging em arquivo (com rotação, em `~/.local/state/ytmusic-tui/log/` no
  Linux) — nunca no stderr, que sujaria a TUI
- Dependabot semanal para as dependências Python (PRs testadas pelo CI)

### Alterado

- A TUI foi dividida em módulos menores: `tui/screens.py` (tela principal),
  `tui/widgets.py` (widgets) e controllers de reprodução, downloads e
  biblioteca — o `app.py` ficou com o ciclo de vida do app e o `main()`
  (sem mudança de comportamento)

### Corrigido

- Falha ao carregar a biblioteca local não parece mais uma "biblioteca vazia":
  o erro aparece na aba 📚 (com a mensagem padrão preservada para quando o
  carregamento voltar a funcionar) e fica registrado no log

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
- 55 testes automatizados (offline, com mocks) + testes de integração opcionais
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
