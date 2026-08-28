"""Consulta ao OCS Inventory: quais maquinas um usuario aparece usando.

Fala com o CONSOLE WEB, nao com a REST API. A REST esta instalada no
servidor mas responde 500, entao o console e o unico caminho de leitura
disponivel hoje. Isso tem consequencias que estao codificadas aqui:

  * a busca do console e um DataTables server-side, entao a requisicao leva
    a definicao das 41 colunas, do jeito que o navegador manda;
  * o token CSRF tem NOME dinamico (CSRF_8, CSRF_15...), entao e obrigatorio
    abrir uma pagina protegida antes de cada busca para le-lo;
  * varios campos voltam embrulhados em HTML, porque o mesmo JSON alimenta a
    tabela do navegador.

O dado tambem tem um limite proprio: o OCS guarda o usuario da ULTIMA coleta
do agente, nao quem esta logado agora. Por isso todo resultado carrega
lastdate e a idade em dias, para a interface poder marcar o que esta velho.

Se o console for atualizado, isto quebra. Quando quebrar, tem que quebrar
ALTO: qualquer resposta que nao seja JSON vira OcsError, nunca lista vazia.
Lista vazia significaria "esse usuario nao tem maquina", que e uma resposta
errada, nao um erro.

Depende de config e applog.
"""

from datetime import datetime
from html import unescape
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import OCS_SEARCH_LIMIT, OCS_STALE_DAYS, OCS_TIMEOUT_SECONDS
from .applog import audit_log, log_exception


class OcsError(Exception):
    """Falha ao consultar o OCS, com mensagem ja legivel para o usuario."""


# Colunas exatamente como o console as envia. A ordem importa: o PHP indexa
# parte da consulta por posicao, entao replicar o que o navegador manda e o
# que garante o mesmo resultado. Conferido contra uma captura HAR real.
COLUNAS = [
    ("CHECK", "CHECK", False), ("TAG", "a.TAG", True), ("lastdate", "h.lastdate", True),
    ("name", "h.name", True), ("ID", "h.ID", True), ("userid", "h.userid", True),
    ("osname", "h.osname", True), ("capa", "capa", True), ("processors", "h.processors", True),
    ("workgroup", "h.workgroup", True), ("osversion", "h.osversion", True),
    ("oscomments", "h.oscomments", True), ("processort", "h.processort", True),
    ("processorn", "h.processorn", True), ("swap", "h.swap", True),
    ("lastcome", "h.lastcome", True), ("quality", "h.quality", True),
    ("fidelity", "h.fidelity", True), ("description", "h.description", True),
    ("wincompany", "h.wincompany", True), ("winowner", "h.winowner", True),
    ("useragent", "h.useragent", True), ("archive", "h.archive", True),
    ("smanufacturer", "e.smanufacturer", True), ("bmanufacturer", "e.bmanufacturer", True),
    ("ssn", "e.ssn", True), ("smodel", "e.smodel", True), ("bversion", "e.bversion", True),
    ("ipaddr", "h.ipaddr", True), ("userdomain", "h.userdomain", True),
    ("ARCH", "h.ARCH", True), ("bdate", "e.bdate", True), ("vname", "vname", True),
    ("category_name", "ac.category_name", True), ("macaddr", "n.macaddr", True),
    ("ipmask", "n.ipmask", True), ("ipgateway", "n.ipgateway", True),
    ("ipsubnet", "n.ipsubnet", True), ("ARCHIVER", "ARCHIVER", False),
    ("SUP", "SUP", False), ("ACTIONS", "ACTIONS", False),
]


# ----------------------------------------------------------------- puras


def clean_text(value) -> str:
    """Tira o HTML que o console mistura nos dados.

    O campo name volta como <a href='...'>W04-554-045901</a>, porque o mesmo
    JSON alimenta a tabela do navegador. Para conectar precisamos do nome
    puro, nao do link.
    """
    texto = re.sub(r"<[^>]*>", " ", str(value if value is not None else ""))
    return " ".join(unescape(texto).split())


def extract_systemid(value) -> str:
    """ID do computador no OCS, que vem escondido no href do proprio nome."""
    achado = re.search(r"systemid=(\d+)", str(value or ""))
    return achado.group(1) if achado else ""


def inventory_age_days(lastdate: str, now: datetime | None = None) -> int | None:
    """Idade do ultimo inventario em dias, ou None se a data nao for legivel."""
    texto = clean_text(lastdate)
    if not texto:
        return None
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            quando = datetime.strptime(texto, formato)
        except ValueError:
            continue
        referencia = now or datetime.now()
        return max((referencia - quando).days, 0)
    return None


def parse_search_response(payload: dict, now: datetime | None = None) -> dict:
    """Transforma a resposta do DataTables em algo que a interface consome.

    Devolve maquinas ja limpas e ordenadas da coleta mais recente para a mais
    antiga, mais o total que o servidor diz ter encontrado. A comparacao entre
    o que veio e esse total e o que detecta truncamento: pedir 200 e receber
    200 de um total de 340 nao pode virar "achei 200" silenciosamente.
    """
    if not isinstance(payload, dict):
        raise OcsError("O OCS respondeu num formato inesperado.")

    linhas = payload.get("data")
    if not isinstance(linhas, list):
        raise OcsError("A resposta do OCS não trouxe a lista de máquinas.")

    maquinas = []
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        lastdate = clean_text(linha.get("lastdate"))
        maquinas.append({
            "name": clean_text(linha.get("name")),
            "ip": clean_text(linha.get("ipaddr")),
            "user": clean_text(linha.get("userid")),
            "tag": clean_text(linha.get("TAG")),
            "domain": clean_text(linha.get("userdomain")),
            "lastdate": lastdate,
            "age_days": inventory_age_days(lastdate, now),
            "systemid": extract_systemid(linha.get("name")),
        })

    # Mais recente primeiro: e a linha em que se deve confiar quando a mesma
    # maquina aparece duas vezes, o que acontece quando ela foi renomeada e o
    # registro antigo ficou para tras com o mesmo IP.
    maquinas.sort(key=lambda m: m["lastdate"], reverse=True)

    total = payload.get("recordsFiltered")
    total = total if isinstance(total, int) and total >= 0 else len(maquinas)

    return {
        "machines": maquinas,
        "total": total,
        "truncated": total > len(maquinas),
    }


def count_stale(machines: list[dict], stale_days: int = OCS_STALE_DAYS) -> int:
    """Quantas maquinas nao inventariam ha mais de stale_days."""
    return sum(
        1 for m in machines
        if isinstance(m.get("age_days"), int) and m["age_days"] > stale_days
    )


def is_stale(machine: dict, stale_days: int = OCS_STALE_DAYS) -> bool:
    idade = machine.get("age_days")
    return isinstance(idade, int) and idade > stale_days


def connection_target(machine: dict) -> str:
    """Endereco para conectar: IP quando existe, senao o nome da maquina.

    Nem toda linha tem IP. O nome funciona porque e o mesmo padrao usado no
    hosts.json, entao resolve por DNS na rede interna.
    """
    return (machine.get("ip") or "").strip() or (machine.get("name") or "").strip()


# Estados da conferencia ao vivo. O que interessa de verdade e DIFFERENT:
# significa que o inventario aponta uma pessoa e outra esta usando a maquina
# agora, que e exatamente o caso que a data antiga nao consegue revelar.
SESSION_UNKNOWN = "desconhecido"
SESSION_SAME = "igual"
SESSION_DIFFERENT = "diferente"
SESSION_NONE = "sem_sessao"
SESSION_OFFLINE = "offline"
SESSION_ERROR = "erro"


def normalize_username(value) -> str:
    """Compara usuarios ignorando dominio e caixa.

    O OCS grava "ricardo.kaipper" e o qwinsta pode devolver "CORP\\ricardo.kaipper"
    ou "Ricardo.Kaipper". Sem normalizar, a mesma pessoa pareceria duas.
    """
    texto = clean_text(value).strip()
    if not texto:
        return ""
    if "\\" in texto:
        texto = texto.rsplit("\\", 1)[-1]
    if "@" in texto:
        texto = texto.split("@", 1)[0]
    return texto.casefold()


def session_status(ocs_user, live_result) -> str:
    """Compara o usuario do inventario com quem o qwinsta viu agora.

    live_result vem de _query_logged_user(): pode ser uma lista de usuarios
    separada por virgula, ou um dos marcadores OFFLINE / VAZIO / SEM HOST /
    ERRO.
    """
    bruto = clean_text(live_result).strip()
    if not bruto:
        return SESSION_UNKNOWN

    marcador = bruto.upper()
    if marcador == "OFFLINE":
        return SESSION_OFFLINE
    if marcador == "VAZIO":
        return SESSION_NONE
    if marcador == "SEM HOST" or marcador.startswith("ERRO"):
        return SESSION_ERROR

    alvo = normalize_username(ocs_user)
    presentes = {normalize_username(parte) for parte in bruto.split(",")}
    presentes.discard("")
    if not presentes:
        return SESSION_NONE
    if alvo and alvo in presentes:
        return SESSION_SAME
    return SESSION_DIFFERENT


def format_session(live_result) -> str:
    """Texto curto para a coluna da sessao ao vivo."""
    bruto = clean_text(live_result).strip()
    if not bruto:
        return ""
    marcador = bruto.upper()
    if marcador == "OFFLINE":
        return "offline"
    if marcador == "VAZIO":
        return "sem sessão"
    if marcador == "SEM HOST":
        return "sem host"
    if marcador.startswith("ERRO"):
        return "erro"
    # Varios usuarios: mostra o primeiro e sinaliza que ha mais.
    partes = [p.strip() for p in bruto.split(",") if p.strip()]
    if len(partes) > 1:
        return f"{partes[0]} +{len(partes) - 1}"
    return partes[0] if partes else ""


def _find_csrf(html: str) -> tuple[str, str] | None:
    """Par (nome, valor) do token, cujo nome muda a cada carregamento."""
    for padrao in (
        r'name=["\'](CSRF_\d+)["\'][^>]*value=["\']([0-9a-fA-F]{8,})["\']',
        r'value=["\']([0-9a-fA-F]{8,})["\'][^>]*name=["\'](CSRF_\d+)["\']',
    ):
        achado = re.search(padrao, html)
        if achado:
            a, b = achado.group(1), achado.group(2)
            return (a, b) if a.startswith("CSRF") else (b, a)
    return None


def build_search_body(term: str, csrf: tuple[str, str] | None, limit: int) -> bytes:
    campos: list[tuple[str, str]] = [("draw", "1")]

    for indice, (data, nome, pesquisavel) in enumerate(COLUNAS):
        campos += [
            (f"columns[{indice}][data]", data),
            (f"columns[{indice}][name]", nome),
            (f"columns[{indice}][searchable]", "true" if pesquisavel else "false"),
            (f"columns[{indice}][orderable]", "true" if pesquisavel else "false"),
            (f"columns[{indice}][search][value]", ""),
            (f"columns[{indice}][search][regex]", "false"),
        ]

    campos += [
        ("order[0][column]", "0"),
        ("order[0][dir]", "asc"),
        ("start", "0"),
        ("length", str(limit)),
        ("search[value]", term),
        ("search[regex]", "false"),
        ("SUP_COL", ""),
        ("RAZ", ""),
        ("LANG", ""),
        ("tri_", "h.lastdate"),
        ("sens_", "DESC"),
        ("onglet", "ACTIVE"),
        ("page", "0"),
    ]

    for indice in (0, 1, 2, 3, 5, 6, 28, 40):
        campos.append(("visible_col[]", str(indice)))

    if csrf:
        campos.append(csrf)

    return urllib.parse.urlencode(campos).encode("utf-8")


# ------------------------------------------------------------------ rede


class OcsSession:
    """Sessao autenticada no console. Use search_user()."""

    def __init__(self, base_url: str, timeout: int = OCS_TIMEOUT_SECONDS):
        self.base = str(base_url or "").strip().rstrip("/")
        if not self.base:
            raise OcsError(
                "O endereço do OCS não está configurado.\n\n"
                "Defina em Configurações > OCS Inventory."
            )
        if not self.base.lower().startswith(("http://", "https://")):
            self.base = "http://" + self.base

        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.opener.addheaders = [
            ("User-Agent", "VNC-Menu"),
            ("Accept", "*/*"),
        ]

    def _request(self, path: str, data: bytes | None = None,
                 ajax: bool = False, referer: str | None = None):
        url = self.base + path
        pedido = urllib.request.Request(url, data=data)
        if data is not None:
            pedido.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        if referer:
            pedido.add_header("Referer", referer)
        if ajax:
            pedido.add_header("X-Requested-With", "XMLHttpRequest")
            pedido.add_header("Referer", f"{self.base}/index.php?function=visu_computers")

        try:
            with self.opener.open(pedido, timeout=self.timeout) as resposta:
                tipo = resposta.headers.get("Content-Type", "")
                corpo = resposta.read().decode("utf-8", errors="replace")
                return tipo, corpo
        except urllib.error.HTTPError as exc:
            raise OcsError(f"O OCS respondeu HTTP {exc.code} ({exc.reason}).") from exc
        except urllib.error.URLError as exc:
            raise OcsError(
                f"Não foi possível falar com o OCS em {self.base}.\n\n{exc.reason}"
            ) from exc
        except Exception as exc:
            raise OcsError(f"Falha ao consultar o OCS:\n{exc}") from exc

    def login(self, user: str, password: str) -> None:
        """Autentica e confirma pelo acesso a uma pagina protegida.

        Nao se decide o sucesso pelo conteudo da resposta do POST: a pagina JA
        LOGADA do console continua trazendo um form com LOGIN/PASSWD, entao
        procurar essas strings acusa falha em cima de um login que funcionou.
        Quem decide e o token: se ele aparece numa pagina protegida, a sessao
        vale.
        """
        self._request("/")
        corpo = urllib.parse.urlencode({
            "LOGIN": user,
            "PASSWD": password,
            "Valid_CNX": "Send",
        }).encode("utf-8")
        self._request("/index.php", corpo, referer=f"{self.base}/index.php")

    def _csrf_token(self) -> tuple[str, str] | None:
        _tipo, html = self._request("/index.php?function=visu_computers")
        token = _find_csrf(html)
        if token:
            return token
        # Sem token, o mais provavel e que a sessao nao exista.
        if "Valid_CNX" in html and "<table" not in html.lower():
            raise OcsError(
                "O OCS recusou o login.\n\n"
                "Confira usuário e senha em Configurações > OCS Inventory."
            )
        return None

    def search_user(self, term: str, limit: int = OCS_SEARCH_LIMIT) -> dict:
        term = str(term or "").strip()
        if not term:
            raise OcsError("Digite um nome de usuário para buscar.")

        token = self._csrf_token()
        corpo = build_search_body(term, token, limit)
        tipo, texto = self._request(
            "/ajax.php?function=visu_computers&no_header=true&no_footer=true",
            corpo,
            ajax=True,
        )

        if "json" not in tipo.lower():
            # Falha ALTA de proposito. Devolver lista vazia aqui viraria
            # "esse usuario nao tem maquina nenhuma", que e mentira.
            raise OcsError(
                "O OCS respondeu algo inesperado no lugar dos dados.\n\n"
                "Isso costuma ser sessão expirada ou mudança no console. "
                "Tente de novo; se persistir, o console pode ter sido atualizado."
            )

        try:
            dados = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise OcsError(f"O OCS devolveu um JSON inválido:\n{exc}") from exc

        return parse_search_response(dados)


def search_machines_by_user(base_url: str, user: str, password: str,
                            term: str, limit: int = OCS_SEARCH_LIMIT) -> dict:
    """Login e busca numa chamada. Feito para rodar em thread separada."""
    sessao = OcsSession(base_url)
    sessao.login(user, password)
    resultado = sessao.search_user(term, limit)
    try:
        audit_log(
            "OCS_USER_SEARCH",
            f"termo={term}; encontrados={len(resultado['machines'])}; "
            f"total={resultado['total']}; truncado={resultado['truncated']}",
        )
    except Exception:
        log_exception()
    return resultado
