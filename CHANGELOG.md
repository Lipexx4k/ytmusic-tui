# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.
O formato segue livremente o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto usa [versionamento semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Adicionado

- Publicação atômica de downloads (T03): o arquivo vai para um temporário em
  `download_dir/.tmp/` (mesmo filesystem) e é publicado com `os.replace` +
  `fsync`, com reserva exclusiva do nome final — nada é sobrescrito em
  silêncio e duas tarefas não disputam o mesmo arquivo
- Se o arquivo de destino já existir, o download não acontece: o existente é
  validado, registrado na biblioteca (bitrate desconhecido) e a faixa é
  concluída; se for inválido, a tarefa falha sem apagar nada
- Reconciliação na inicialização (T03): arquivos válidos sem registro são
  importados para a biblioteca, arquivos inválidos vão para
  `download_dir/.quarantine/` (modo 0700), registros sem arquivo são
  relatados no log e temporários/`.part` com mais de 24 h e prefixo do
  próprio app são removidos — nunca arquivos finais
- Downloads que ficaram pela metade sobrevivem ao encerramento (T04): o
  ciclo de vida das tarefas é persistido em tabela própria
  (`download_tasks`) e, na execução seguinte, aparecem como interrompidos na
  aba 📥, onde `r` retoma e `d` descarta
- Retomar nunca reaproveita o `.part`: é uma nova tarefa (com `retry_of`) e
  os temporários da tentativa antiga — inclusive o lock `.reserva` órfão de
  um encerramento abrupto — são descartados antes de baixar de novo; o
  arquivo final do usuário nunca é tocado
- Temporários/`.part` de download aguardando decisão não são mais removidos
  pela limpeza de 24 h: com dono, a decisão (retomar/descartar) é do
  usuário; sem dono, a política de idade continua valendo
- O banco da biblioteca agora tem migrações versionadas (T05): a versão do
  esquema fica gravada no próprio banco e um banco criado por versões
  anteriores é migrado sem perder dados; banco novo já nasce no esquema
  atual, estampado — e esquema mais novo que o app vira erro claro, nunca
  `create_all` silencioso
- Backup automático do banco antes de qualquer migração (via `VACUUM INTO`,
  nunca cópia de arquivo em uso): fica na pasta `backups/`, ao lado do
  banco, com retenção dos 5 mais recentes — backup falhou, não migra
- Diagnóstico de integridade do banco (`PRAGMA integrity_check`) disponível
  por API para o futuro comando de diagnóstico (T13)
- Faixas cujo arquivo registrado não está mais no disco são marcadas como
  ausentes (`is_missing`, migração v2 do banco): a reconciliação marca na
  primeira ocorrência e desmarca quando o arquivo volta; registrar o arquivo
  de novo limpa a marca — "registro sem arquivo" deixa de viver só no log
- Mensagens da aba Biblioteca específicas por tipo de falha (permissão,
  banco corrompido, esquema incompatível, backup/migração falhados, banco em
  uso): cada caso explica o que houve e o que fazer, em vez de um erro
  genérico — inclusive quando a falha acontece na abertura do banco
- Aviso ao tocar uma faixa cujo arquivo registrado não está mais no disco
  (em vez de mandar o player abrir um caminho inexistente); a reconciliação
  marca a faixa como ausente na passagem seguinte

### Alterado

- Downloads usam uma máquina de estados explícita (T02): novos estados
  "validando" e "interrompido"; cancelar não afeta as outras tarefas e nunca
  sobrescreve um resultado já finalizado; encerrar o app marca downloads em
  voo como interrompidos (retomada e descarte na aba 📥)
- Faixas diferentes que gerariam o mesmo arquivo final não são mais
  enfileiradas em paralelo (evita disputa pelo mesmo caminho de saída)
- A tabela de downloads não duplica mais a linha da tarefa em execução
  (fila + ativos eram somados) e a linha selecionada é a referência das
  ações de retomar/descartar
- Falhas do banco da biblioteca têm erros tipados (inacessível, sem
  permissão, esquema incompatível, corrompido): a mensagem mostrada diz o
  caso real e a inicialização do app nunca cria/derruba tabelas em
  silêncio — e falha de banco não derruba o app

### Corrigido

- Instalação limpa do wheel/sdist não incluía `tui/app.tcss` (único arquivo
  não-`.py` de runtime do pacote): o app morria no startup com
  `StylesheetError` — o CSS passa a ser empacotado explicitamente, o job
  "pacote" do CI confere o conteúdo do artefato (wheel e sdist) antes de
  instalar e uma guarda de fonte garante o arquivo ao lado de `app.py`
  (T06.1)

### Segurança

- Endurecimento geral (T06): o caminho de cada download é normalizado uma
  única vez e o destino é contido dentro de `download_dir` **depois** de
  resolver symlinks e `..` — nada é criado, baixado ou publicado fora da
  pasta de mídia, nem com entrada hostil, banco adulterado ou colisão entre
  tarefas
- yt-dlp com limites de rede (T06): timeout de socket de 30 s e 3
  retentativas (3 para fragmentos) — stream travado vira falha clara em vez
  de download pendurado para sempre
- yt-dlp ou ffmpeg ausente vira falha da tarefa com o que instalar (T06); o
  app avisa uma vez por execução quando só o yt-dlp falta, e o ffmpeg só é
  exigido na hora do download
- Ciclo de vida do mpv explícito (T06): `start`/`shutdown` idempotentes,
  falha ao iniciar vira estado de erro na TUI (nunca exceção solta) e
  `LC_NUMERIC=C` é fixado ao criar cada instância
- Permissões privadas para dados e trabalho (T06): diretórios internos
  (config, dados, cache, log, backups, `.tmp`, `.quarantine`) nascem 0700 e
  arquivos (banco + sidecars, backups, log rotacionado, `config.toml`) 0600
  **mesmo com `umask 0`**; o que já existe só é apertado (nunca afrouxado),
  com registro no log — e `download_dir` é mídia do usuário, nunca é
  chmodado
- Mensagens de erro (yt-dlp, mpv, banco) exibidas na TUI são mascaradas
  (T06): HOME vira `~` e URLs perdem query/credenciais — o log preserva o
  detalhe cru
- `set_concurrent` valida o valor recebido (tipo e faixa 1–10) em vez de
  ajustar em silêncio (T06); a aba Config normaliza antes de aplicar e avisa
  em caso de valor inválido

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
