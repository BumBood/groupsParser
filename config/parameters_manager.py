import yaml
from pathlib import Path
from typing import Any

class ParametersManagerMeta(type):
    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        cls._load_config()
        
        # Создаем свойства для всех параметров из конфига
        for param_name in cls._config.keys():
            setattr(cls, param_name, property(
                fget=lambda self, _name=param_name: self.get_parameter(_name),
                fset=lambda self, value, _name=param_name: self.set_parameter(_name, value)
            ))
        
        return cls

class ParametersManager(metaclass=ParametersManagerMeta):
    _config = {}
    _config_path = Path("config/parameters.yaml")

    @classmethod
    def _load_config(cls) -> None:
        """Загружает конфигурацию из файла"""
        if not cls._config_path.exists():
            raise FileNotFoundError(f"Конфигурационный файл не найден: {cls._config_path}")
            
        with open(cls._config_path, 'r') as file:
            cls._config = yaml.safe_load(file)['parameters']

    @classmethod
    def get_parameter(cls, param_name: str) -> Any:
        """Получает значение параметра по имени"""
        if param_name not in cls._config:
            raise KeyError(f"Параметр {param_name} не найден в конфигурации")
        return cls._config[param_name]

    @classmethod
    def set_parameter(cls, param_name: str, value: Any) -> None:
        """Устанавливает новое значение параметра и сохраняет в файл"""
        cls._config[param_name] = value
        
        with open(cls._config_path, 'w') as file:
            yaml.dump({'parameters': cls._config}, file)