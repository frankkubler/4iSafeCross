# Hooks git versionnés

## Activation (une fois par clone)

```sh
git config core.hooksPath .githooks
```

## Hooks

| Hook | Rôle |
|---|---|
| `pre-commit` | Refuse tout commit introduisant un secret (gitleaks, scan de l'index). Nécessite `gitleaks` dans le PATH ; sans lui, avertit et laisse passer — le job CI `security:gitleaks` reste bloquant. |

## Alternative : framework pre-commit

Si tu utilises [pre-commit](https://pre-commit.com) :

```sh
uv tool install pre-commit
pre-commit install
```

La configuration est dans [`.pre-commit-config.yaml`](../.pre-commit-config.yaml)
à la racine. Les deux mécanismes peuvent coexister.
