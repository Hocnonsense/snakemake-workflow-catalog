# Browser deploy app

A stlite (Streamlit on WASM) app that deploys a catalog workflow into a new GitHub repository, lets the user edit its configuration, and pushes it.

It is served as a static page at `/_static/webapp/`. The workflow page button links to it with `?repo=<owner>/<name>&ref=<tag>`.

## Connect to GitHub

GitHub's OAuth flow needs a small server to perform the flow or hold the client secret. A static page therefore cannot run the device flow or exchange an authorization code.
Until then the app uses a personal access token. It is kept in `st.session_state` only, which means it is gone after a page reload.

## Local development

Build the static tree and serve the site:

```bash
python scripts/build-webapp.py
python -m http.server -d build/html 8000
# open http://localhost:8000/docs/workflows/<owner>/<name>.html
```

The app can also be run with normal Streamlit from the repository root:

```bash
pip install streamlit pyyaml jsonschema

mkdir -p /tmp/webapp-dev && cd /tmp/webapp-dev
echo '{"repo":"owner/name","ref":"v1"}' > bootstrap.json
streamlit run webapp/app.py
```

## Tests

Pure logic tests:

```bash
pixi run -e webapp test-webapp
```

AppTest UI tests (the `webapp` environment adds Streamlit):

```bash
pixi run -e webapp test-webapp-ui
```

## Compatibility contract

`snakedeploy` deploys by shelling out to `git`, which is unavailable in the browser. The app therefore cannot call it at runtime. `catalog_webapp/deploy.py` is an independent implementation that must produce the same files as snakedeploy 0.11.x:

- the generated `workflow/Snakefile` (module declaration, `configfile`, `use rule *`);
- copied `config/`, `profiles/`, and the root license;
- an empty `config/config.yaml` when the source has no `config/`.

If snakedeploy gains a pure-Python/API git layer later, this module can be replaced by a direct dependency.
