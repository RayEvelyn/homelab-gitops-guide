from pathlib import Path
import re,subprocess,yaml
for f in [Path('.gitlab-ci.yml'),*Path('.gitlab').rglob('*.example'),*Path('examples').rglob('*.yaml'),*Path('.github').rglob('*.yml')]:
    list(yaml.safe_load_all(f.read_text()))
for f in [Path('README.md'),*Path('docs').glob('*.md')]:
    for block in re.findall(r"```bash\n(.*?)```",f.read_text(),re.S):
        subprocess.run(['bash','-n'],input=block,text=True,check=True)
print('YAML and embedded Bash valid; no deployment commands executed')
