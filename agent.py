#!/usr/bin/env python3
"""Agente de programação para projetos locais usando NVIDIA Build."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "moonshotai/kimi-k3-instruct"
MAX_TOOL_ROUNDS = 20


class AgentError(RuntimeError):
    """Erro compreensível devolvido ao modelo."""


class SearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and "result__a" in (attrs_dict.get("class") or ""):
            self._in_link = True
            self._href = attrs_dict.get("href") or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            title = "".join(self._text).strip()
            if title and self._href:
                self.results.append({"title": title, "url": self._href})
            self._in_link = False


@dataclass
class ProjectWorkspace:
    root: Path
    confirm_delete: Callable[[Path], bool]

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    def path(self, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise AgentError("Use um caminho relativo não vazio dentro do projeto.")
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise AgentError("O caminho sai da raiz do projeto e foi bloqueado.")
        return candidate

    def list_files(self, relative_path: str = ".") -> str:
        base = self.root if relative_path == "." else self.path(relative_path)
        if not base.exists():
            raise AgentError("O caminho não existe.")
        if base.is_file():
            return str(base.relative_to(self.root))
        files = [str(item.relative_to(self.root)) for item in base.rglob("*")]
        return "\n".join(sorted(files)[:500]) or "(diretório vazio)"

    def read_file(self, relative_path: str) -> str:
        target = self.path(relative_path)
        if not target.is_file():
            raise AgentError("O ficheiro não existe ou não é um ficheiro normal.")
        if target.stat().st_size > 1_000_000:
            raise AgentError("O ficheiro excede o limite de leitura de 1 MB.")
        return target.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str) -> str:
        target = self.path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Escrito: {target.relative_to(self.root)} ({len(content)} caracteres)"

    def edit_file(self, relative_path: str, old_text: str, new_text: str) -> str:
        current = self.read_file(relative_path)
        occurrences = current.count(old_text)
        if occurrences != 1:
            raise AgentError(f"A edição exige exatamente uma ocorrência; encontradas: {occurrences}.")
        return self.write_file(relative_path, current.replace(old_text, new_text, 1))

    def delete_path(self, relative_path: str) -> str:
        target = self.path(relative_path)
        if not target.exists() and not target.is_symlink():
            raise AgentError("O caminho não existe.")
        if not self.confirm_delete(target):
            return "Eliminação cancelada pelo utilizador."
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        return f"Eliminado: {target.relative_to(self.root)}"


def web_search(query: str, max_results: int = 5) -> str:
    if not query.strip():
        raise AgentError("A pesquisa não pode estar vazia.")
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ProjectAgent/1.0)"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            page = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        raise AgentError(f"Não foi possível pesquisar na web: {error.reason}") from error
    parser = SearchResultParser()
    parser.feed(page)
    results = parser.results[:max(1, min(max_results, 10))]
    return json.dumps(results, ensure_ascii=False) if results else "Sem resultados."


TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "list_files", "description": "Lista ficheiros e diretórios dentro do projeto.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Caminho relativo; use '.' para a raiz."}}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Lê um ficheiro UTF-8 dentro do projeto.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Cria ou substitui um ficheiro UTF-8 dentro do projeto.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Substitui uma ocorrência exata num ficheiro existente.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {"name": "delete_path", "description": "Elimina um ficheiro ou diretório do projeto; requer confirmação local por defeito.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Pesquisa na web e devolve títulos e URLs relevantes.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}}},
]


class NvidiaAgent:
    def __init__(self, workspace: ProjectWorkspace, api_key: str, model: str) -> None:
        self.workspace = workspace
        self.api_key = api_key
        self.model = model

    def _request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload = json.dumps({"model": self.model, "messages": messages, "tools": TOOLS, "tool_choice": "auto", "temperature": 0.2}).encode()
        request = urllib.request.Request(NVIDIA_API_URL, data=payload, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise AgentError(f"A API NVIDIA respondeu {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise AgentError(f"Não foi possível contactar a API NVIDIA: {error.reason}") from error

    def _run_tool(self, name: str, arguments: dict[str, Any]) -> str:
        handlers: dict[str, Callable[..., str]] = {
            "list_files": self.workspace.list_files, "read_file": self.workspace.read_file,
            "write_file": self.workspace.write_file, "edit_file": self.workspace.edit_file,
            "delete_path": self.workspace.delete_path, "web_search": web_search,
        }
        try:
            return handlers[name](**arguments)
        except (AgentError, TypeError, OSError) as error:
            return f"Erro na ferramenta: {error}"

    def run(self, task: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "És um agente de programação. Trabalha apenas dentro da raiz do projeto através das ferramentas. Inspeciona antes de alterar, pesquisa quando precisares de factos atuais e explica resumidamente o que fizeste. Nunca inventes resultados de ferramentas."},
            {"role": "user", "content": task},
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            response = self._request(messages)
            message = response["choices"][0]["message"]
            messages.append(message)
            calls = message.get("tool_calls") or []
            if not calls:
                return message.get("content") or "Tarefa concluída."
            for call in calls:
                try:
                    arguments = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}
                result = self._run_tool(call["function"]["name"], arguments)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        raise AgentError(f"Limite de {MAX_TOOL_ROUNDS} rondas de ferramentas atingido.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", help="Tarefa para o agente; omita para modo interativo.")
    parser.add_argument("--project", default=".", help="Raiz do projeto a gerir (predefinição: diretório atual).")
    parser.add_argument("--model", default=os.getenv("NVIDIA_MODEL", DEFAULT_MODEL), help="Modelo NVIDIA Build.")
    parser.add_argument("--yes", action="store_true", help="Autoriza eliminações sem confirmação.")
    args = parser.parse_args()
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        parser.error("Defina NVIDIA_API_KEY antes de iniciar o agente.")

    def confirm_delete(path: Path) -> bool:
        if args.yes:
            return True
        return input(f"Eliminar {path}? [s/N] ").strip().lower() in {"s", "sim", "y", "yes"}

    agent = NvidiaAgent(ProjectWorkspace(Path(args.project), confirm_delete), api_key, args.model)
    if args.task:
        print(agent.run(args.task))
        return 0
    print(f"Agente pronto para {Path(args.project).resolve()}. Escreva 'sair' para terminar.")
    while True:
        try:
            task = input("\nTarefa> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if task.lower() in {"sair", "exit", "quit"}:
            return 0
        if task:
            try:
                print(agent.run(task))
            except AgentError as error:
                print(f"Erro: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
