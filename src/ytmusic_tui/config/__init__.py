"""Configuração centralizada da aplicação."""

import json
import os
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir, user_config_dir, user_data_dir
from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# Caminho padrão do arquivo de configuração TOML.
# É calculado independentemente da instância para evitar dependência circular
# (config_dir é uma das configurações carregadas do próprio arquivo).
DEFAULT_CONFIG_FILE = Path(user_config_dir("ytmusic-tui")) / "config.toml"


def _toml_literal(value: object) -> str:
    """Serializa um valor simples para TOML (str, bool, int, float)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


class Settings(BaseSettings):
    """Configurações da aplicação carregadas de arquivo e variáveis de ambiente."""

    model_config = SettingsConfigDict(
        env_prefix="YTMUSIC_",
        case_sensitive=False,
        extra="ignore",
        toml_file=DEFAULT_CONFIG_FILE,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Define a precedência das fontes de configuração.

        Ordem (maior prioridade primeiro):
        1. Valores passados no construtor
        2. Variáveis de ambiente (YTMUSIC_*)
        3. Arquivo TOML (~/.config/ytmusic-tui/config.toml)
        4. Secrets de arquivos
        """
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @field_validator(
        "config_dir",
        "data_dir",
        "cache_dir",
        "download_dir",
        mode="before",
    )
    @classmethod
    def _expand_user_path(cls, value: object) -> object:
        """Expande '~' em caminhos vindos do arquivo de configuração."""
        if isinstance(value, (str, os.PathLike)):
            return Path(os.path.expanduser(str(value)))
        return value

    # Diretórios base
    config_dir: Path = Field(
        default_factory=lambda: Path(user_config_dir("ytmusic-tui")),
        description="Diretório de configuração",
    )
    data_dir: Path = Field(
        default_factory=lambda: Path(user_data_dir("ytmusic-tui")),
        description="Diretório de dados (banco de dados, downloads)",
    )
    cache_dir: Path = Field(
        default_factory=lambda: Path(user_cache_dir("ytmusic-tui")),
        description="Diretório de cache",
    )

    # Player (mpv)
    mpv_volume: int = Field(default=50, ge=0, le=100, description="Volume inicial (0-100)")
    mpv_audio_quality: str = Field(
        default="high",
        description="Qualidade de áudio: low, medium, high, best",
    )

    # Download
    download_dir: Path = Field(
        default_factory=lambda: Path.home() / "Music" / "YouTube Music",
        description="Diretório padrão para downloads",
    )
    download_format: str = Field(
        default="mp3",
        description="Formato de download: mp3, opus, m4a, flac",
    )
    download_quality: str = Field(
        default="320",
        description="Qualidade do áudio em kbps (para mp3) ou 'best'",
    )
    download_concurrent: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Downloads simultâneos",
    )
    embed_metadata: bool = Field(
        default=True,
        description="Inserir metadados (tags ID3, capa) nos arquivos",
    )

    # Biblioteca local
    library_db_name: str = Field(
        default="library.db",
        description="Nome do arquivo do banco de dados SQLite",
    )

    # Interface TUI
    show_notifications: bool = Field(
        default=True,
        description="Mostrar notificações toast",
    )
    auto_play_next: bool = Field(
        default=True,
        description="Reproduzir próxima música automaticamente",
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Garantir que diretórios existam
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    @property
    def library_db_path(self) -> Path:
        """Caminho completo do banco de dados da biblioteca."""
        return self.data_dir / self.library_db_name

    def update_and_save(self, **updates: Any) -> None:
        """Atualiza valores em memória e persiste no arquivo TOML.

        Preserva chaves já existentes no arquivo (inclusive desconhecidas).
        """
        for key, value in updates.items():
            if key not in type(self).model_fields:
                raise KeyError(f"Configuração desconhecida: {key}")
            setattr(self, key, value)
        self._save_toml(updates)

    def _save_toml(self, updates: dict[str, Any]) -> None:
        """Reescreve o TOML aplicando as atualizações."""
        import tomllib

        # ``model_config`` é um TypedDict: o valor de ``toml_file`` pode ser
        # Path ou str, então normalizamos antes de usar.
        configured = self.model_config.get("toml_file")
        path = Path(str(configured)) if configured else DEFAULT_CONFIG_FILE
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError:
                data = {}
        for key, value in updates.items():
            data[key] = str(value) if isinstance(value, Path) else value
        lines = [f"{key} = {_toml_literal(value)}" for key, value in data.items()]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Instância global de configurações
settings = Settings()
