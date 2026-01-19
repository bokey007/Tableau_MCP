# =============================================================================
# Dashboard Configuration Service
# =============================================================================
"""
Loads and manages dashboard-specific configurations from YAML files.
Configs are merged with auto-discovered context to enrich AI responses.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import yaml

from src.core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Configuration Models
# =============================================================================

@dataclass
class KPIConfig:
    """Key Performance Indicator definition."""
    name: str
    field: Optional[str] = None
    formula: Optional[str] = None
    aggregation: str = "sum"
    format: str = "number"
    description: Optional[str] = None
    target: Optional[float] = None
    good_direction: str = "up"  # up, down, neutral


@dataclass
class DashboardConfig:
    """Full dashboard configuration."""
    name: str
    aliases: List[str] = field(default_factory=list)
    description: Optional[str] = None
    owner: Optional[str] = None
    category: Optional[str] = None
    
    kpis: List[KPIConfig] = field(default_factory=list)
    glossary: Dict[str, Any] = field(default_factory=dict)
    fields: Dict[str, Dict] = field(default_factory=dict)
    hierarchies: Dict[str, List[str]] = field(default_factory=dict)
    suggested_questions: List[Any] = field(default_factory=list)
    ai_instructions: Optional[str] = None
    anomaly_thresholds: Dict[str, Any] = field(default_factory=dict)
    
    # Source file for debugging
    _source_file: Optional[str] = None


# =============================================================================
# Configuration Service
# =============================================================================

class DashboardConfigService:
    """Loads and manages dashboard configurations from YAML files."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize the config service.
        
        Args:
            config_dir: Path to configs directory. Defaults to backend/configs/
        """
        if config_dir is None:
            # Default to configs/ relative to backend root
            backend_root = Path(__file__).parent.parent.parent
            config_dir = backend_root / "configs"
        
        self.config_dir = Path(config_dir)
        self.configs: Dict[str, DashboardConfig] = {}
        self._name_index: Dict[str, str] = {}  # lowercase name -> config key
        
        # Load configs on init
        self.load_all_configs()
    
    def load_all_configs(self) -> int:
        """
        Load all YAML configs from the config directory.
        
        Returns:
            Number of configs loaded
        """
        self.configs.clear()
        self._name_index.clear()
        
        if not self.config_dir.exists():
            logger.warning("Config directory not found", path=str(self.config_dir))
            return 0
        
        count = 0
        for yaml_file in self.config_dir.glob("*.yaml"):
            # Skip template
            if yaml_file.name.startswith("_"):
                continue
                
            try:
                config = self._load_config_file(yaml_file)
                if config:
                    key = yaml_file.stem  # filename without extension
                    self.configs[key] = config
                    
                    # Build name index for matching
                    self._index_config(key, config)
                    count += 1
                    
                    logger.info(
                        "Loaded dashboard config",
                        file=yaml_file.name,
                        dashboard=config.name
                    )
            except Exception as e:
                logger.error("Failed to load config", file=yaml_file.name, error=str(e))
        
        logger.info("Config loading complete", count=count)
        return count
    
    def _load_config_file(self, path: Path) -> Optional[DashboardConfig]:
        """Load and parse a single YAML config file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not data:
            return None
        
        dashboard_data = data.get("dashboard", {})
        if not dashboard_data.get("name"):
            logger.warning("Config missing dashboard.name", file=path.name)
            return None
        
        # Parse KPIs
        kpis = []
        for kpi_data in data.get("kpis", []):
            kpis.append(KPIConfig(
                name=kpi_data.get("name", "Unknown"),
                field=kpi_data.get("field"),
                formula=kpi_data.get("formula"),
                aggregation=kpi_data.get("aggregation", "sum"),
                format=kpi_data.get("format", "number"),
                description=kpi_data.get("description"),
                target=kpi_data.get("target"),
                good_direction=kpi_data.get("good_direction", "up")
            ))
        
        # Parse suggested questions (normalize to list of dicts)
        suggested = []
        for q in data.get("suggested_questions", []):
            if isinstance(q, str):
                suggested.append({"question": q})
            else:
                suggested.append(q)
        
        return DashboardConfig(
            name=dashboard_data.get("name"),
            aliases=dashboard_data.get("aliases", []),
            description=dashboard_data.get("description"),
            owner=dashboard_data.get("owner"),
            category=dashboard_data.get("category"),
            kpis=kpis,
            glossary=data.get("glossary", {}),
            fields=data.get("fields", {}),
            hierarchies=data.get("hierarchies", {}),
            suggested_questions=suggested,
            ai_instructions=data.get("ai_instructions"),
            anomaly_thresholds=data.get("anomaly_thresholds", {}),
            _source_file=str(path.name)
        )
    
    def _index_config(self, key: str, config: DashboardConfig) -> None:
        """Build name index for fast matching."""
        # Index main name
        self._name_index[config.name.lower()] = key
        
        # Index aliases
        for alias in config.aliases:
            self._name_index[alias.lower()] = key
    
    def get_config(self, dashboard_name: str) -> Optional[DashboardConfig]:
        """
        Get config for a dashboard by name.
        
        Args:
            dashboard_name: Name of the dashboard (case-insensitive)
            
        Returns:
            DashboardConfig if found, None otherwise
        """
        if not dashboard_name:
            return None
        
        # Try exact match (case-insensitive)
        key = self._name_index.get(dashboard_name.lower())
        if key:
            return self.configs.get(key)
        
        # Try partial match
        name_lower = dashboard_name.lower()
        for indexed_name, key in self._name_index.items():
            if indexed_name in name_lower or name_lower in indexed_name:
                logger.debug(
                    "Partial config match",
                    requested=dashboard_name,
                    matched=indexed_name
                )
                return self.configs.get(key)
        
        return None
    
    def list_configs(self) -> List[Dict[str, Any]]:
        """List all loaded configs with summary info."""
        return [
            {
                "key": key,
                "name": config.name,
                "aliases": config.aliases,
                "category": config.category,
                "kpi_count": len(config.kpis),
                "has_glossary": bool(config.glossary),
                "has_ai_instructions": bool(config.ai_instructions),
                "suggested_questions": len(config.suggested_questions)
            }
            for key, config in self.configs.items()
        ]
    
    def reload_configs(self) -> int:
        """Reload all configs from disk."""
        logger.info("Reloading dashboard configs")
        return self.load_all_configs()


# =============================================================================
# Singleton Instance
# =============================================================================

_config_service_instance: Optional[DashboardConfigService] = None


def get_config_service() -> DashboardConfigService:
    """Get singleton config service instance."""
    global _config_service_instance
    if _config_service_instance is None:
        _config_service_instance = DashboardConfigService()
    return _config_service_instance
