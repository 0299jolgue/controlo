# Project Agent (NVIDIA Build)

Um agente de IA em Python para trabalhar em projetos locais. Usa a API compatível com OpenAI do **NVIDIA Build** e pode listar, ler, criar, editar e eliminar ficheiros, além de pesquisar na web.

## Configuração

1. Crie uma chave de API no NVIDIA Build e exporte-a:

   ```bash
   export NVIDIA_API_KEY='nvapi-...'
   ```

2. Opcionalmente, escolha o modelo disponibilizado na sua conta. O padrão é `moonshotai/kimi-k3-instruct`:

   ```bash
   export NVIDIA_MODEL='moonshotai/kimi-k3-instruct'
   ```

   O nome do modelo é configurável porque a disponibilidade e os modelos gratuitos do catálogo NVIDIA podem mudar. Para usar Kimi K3 quando ele estiver disponível na sua conta, passe o respetivo identificador com `NVIDIA_MODEL` ou `--model`.

## Uso

Execute no projeto que o agente deve gerir:

```bash
python3 agent.py --project /caminho/para/projeto "Analisa o projeto e cria testes para os módulos sem cobertura."
```

Ou abra uma sessão interativa:

```bash
python3 agent.py --project /caminho/para/projeto
```

Por segurança, cada eliminação pede confirmação. Para automatização explícita, use `--yes`:

```bash
python3 agent.py --project /caminho/para/projeto --yes "Remove os ficheiros temporários gerados."
```

## Limites de segurança

* Todas as operações de ficheiro são resolvidas dentro de `--project`; caminhos absolutos e tentativas de sair da raiz são bloqueados.
* A edição só acontece quando o trecho original aparece exatamente uma vez, evitando substituir o local errado.
* A eliminação requer confirmação local por defeito.
* A pesquisa usa DuckDuckGo HTML e devolve títulos/URLs; é independente da chave NVIDIA.

## Testes

```bash
python3 -m unittest -v
```
