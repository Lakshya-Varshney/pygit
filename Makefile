.PHONY: build test repro clean

build:
	python -m zipapp pygit -o pygit.pyz -p "/usr/bin/env python3"

test:
	python -W ignore::ResourceWarning -m unittest discover -s tests -v

repro:
	python -m zipapp pygit -o pygit_build1.pyz -p "/usr/bin/env python3"
	python -m zipapp pygit -o pygit_build2.pyz -p "/usr/bin/env python3"
	@echo "Build 1 hash:" && python -c "import hashlib; print(hashlib.sha256(open('pygit_build1.pyz','rb').read()).hexdigest())"
	@echo "Build 2 hash:" && python -c "import hashlib; print(hashlib.sha256(open('pygit_build2.pyz','rb').read()).hexdigest())"
	@python -c "import hashlib; h1=hashlib.sha256(open('pygit_build1.pyz','rb').read()).hexdigest(); h2=hashlib.sha256(open('pygit_build2.pyz','rb').read()).hexdigest(); assert h1==h2, 'REPRODUCTION FAILED'; print('REPRODUCTION SUCCESS: Hashes match!')"
	@python -c "import os; [os.remove(f) for f in ['pygit_build1.pyz','pygit_build2.pyz'] if os.path.exists(f)]"

clean:
	python -c "import os; [os.remove(f) for f in ['pygit.pyz','pygit_build1.pyz','pygit_build2.pyz'] if os.path.exists(f)]"
	python -c "import os, glob, shutil; [shutil.rmtree(d) for d in glob.glob('**/__pycache__', recursive=True) if os.path.isdir(d)]"
