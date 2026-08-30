.PHONY: build test repro clean

build:
	python -m py_compile pygit_single.py
	@echo "Build complete. pygit_single.py is the runnable artifact - no packaging step."
	@echo "Run with: python pygit_single.py <command>"

test:
	python -W ignore::ResourceWarning -m unittest discover -s tests -v

repro:
	@echo "SHA-256 of pygit_single.py:"
	@python -c "import hashlib; print(hashlib.sha256(open('pygit_single.py','rb').read()).hexdigest())"
	@echo "This is the entire reproducibility guarantee: there is no build or packaging step between this source file and what runs, so this hash is identical on every machine, every time, by construction."

clean:
	python -c "import os, glob, shutil; [shutil.rmtree(d) for d in glob.glob('**/__pycache__', recursive=True) if os.path.isdir(d)]"
