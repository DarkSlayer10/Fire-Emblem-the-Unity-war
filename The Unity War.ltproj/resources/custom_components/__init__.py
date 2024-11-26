import os
import importlib

for module_name in os.listdir(os.path.dirname(__file__)):
    if module_name == '__init__.py' or module_name[-3:] != '.py':
        continue
    print("Importing Custom Components in %s..." % module_name)
    module = importlib.import_module('custom_components.' + module_name[:-3])
    importlib.reload(module)
del module_name