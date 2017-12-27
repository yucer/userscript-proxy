from typing import Optional, Iterable, List, Callable, Pattern, Match
import glob, os, re
from bs4 import BeautifulSoup, Comment, Doctype
from mitmproxy import ctx, http
import shlex
import warnings
from lib.metadata import MetadataError
import lib.userscript as userscript
from lib.userscript import Userscript, UserscriptError, document_end, document_start, document_idle
from lib.utilities import first, second

def stringifyVersion(version: str) -> str:
    return VERSION_PREFIX + version

VERSION: str = "0.2.0"
VERSION_PREFIX: str = "v"
APP_NAME: str = "Userscript Proxy"
WELCOME_MESSAGE: str = APP_NAME + " " + stringifyVersion(VERSION)
DIRS_USERSCRIPTS: List[str] = ["userscripts"]
PATTERN_USERSCRIPT: str = "*.user.js"
RELEVANT_CONTENT_TYPES: List[str] = ["text/html", "application/xhtml+xml"]
CHARSET_DEFAULT: str = "utf-8"
REGEX_CHARSET: Pattern = re.compile(r"charset=([^;\s]+)")
TAB: str = "    "
LIST_ITEM_PREFIX: str = TAB + "• "
HTML_PARSER: str = "html.parser"
INFO_COMMENT_PREFIX: str = f"""
[{WELCOME_MESSAGE}]
"""

def logInfo(s: str) -> None:
    try:
        ctx.log.info(s)
    except Exception:
        print(s)

def logWarning(s: str) -> None:
    try:
        ctx.log.warn(s)
    except Exception:
        print(s)

def logError(s: str) -> None:
    try:
        ctx.log.error(s)
    except Exception:
        print(s)

def itemList(strs: Iterable[str]) -> str:
    return "\n".join(map(lambda s: LIST_ITEM_PREFIX + s, strs))

def indexOfDoctype(soup: BeautifulSoup) -> Optional[int]:
    index: int = 0
    for item in soup.contents:
        if isinstance(item, Doctype):
            return index
        index += 1
    return None

class UserscriptInjector:
    def __init__(self):
        self.userscripts: List[Userscript] = []
        logInfo("")
        logInfo("╔═" + "═" * len(WELCOME_MESSAGE) + "═╗")
        logInfo("║ " +           WELCOME_MESSAGE  + " ║")
        logInfo("╚═" + "═" * len(WELCOME_MESSAGE) + "═╝")
        logInfo("")
        logInfo("Loading userscripts ...")
        loadedUserscripts: List[Tuple[Userscript, str]] = []
        for directory in DIRS_USERSCRIPTS:
            logInfo("Looking for userscripts (`"+PATTERN_USERSCRIPT+"`) in directory `"+directory+"` ...")
            try:
                os.chdir(directory)
            except FileNotFoundError:
                logWarning("Directory `"+directory+"` does not exist.")
                continue
            except PermissionError:
                logError("Permission was denied when trying to read directory `"+DIR_USERSCRIPTS+"`.")
                continue

            for unsafe_filename in glob.glob(PATTERN_USERSCRIPT):
                filename = shlex.quote(unsafe_filename)
                logInfo("Loading " + filename + " ...")
                try:
                    content = open(filename).read()
                except PermissionError:
                    logError("Could not read file `"+filename+"`: Permission denied.")
                    continue
                except Exception as e:
                    logError("Could not read file `"+filename+"`: " + str(e))
                    continue
                try:
                    loadedUserscripts.append((userscript.create(content), filename))
                except MetadataError as err:
                    logError("Metadata error:")
                    logError(str(err))
                    continue
                except UserscriptError as err:
                    logError("Userscript error:")
                    logError(str(err))
                    continue

        logInfo("")
        logInfo(str(len(loadedUserscripts)) + " userscript(s) loaded:")
        logInfo(itemList(map(
            lambda s: f"{first(s).name} ({second(s)})",
            loadedUserscripts
        )))
        logInfo("")
        self.userscripts = list(map(first, loadedUserscripts))


    def response(self, flow: http.HTTPFlow):
        HEADER_CONTENT_TYPE: str = "Content-Type"
        if HEADER_CONTENT_TYPE in flow.response.headers:
            contentType: str = flow.response.headers[HEADER_CONTENT_TYPE];
            if any(map(lambda t: t in contentType, RELEVANT_CONTENT_TYPES)):
                # Response is a web page; proceed.
                insertedScripts: List[str] = []
                soup = BeautifulSoup(flow.response.content, HTML_PARSER)
                isApplicable: Callable[[Userscript], bool] = userscript.applicableChecker(flow.request.url)
                for script in self.userscripts:
                    if isApplicable(script):
                        logInfo(f"Injecting {script.name} into {flow.request.url} ...")
                        insertedScripts.append(script.name)
                        tag = soup.new_tag("script")
                        if script.runAt == document_start:
                            tag.string = script.content
                            soup.head.append(tag)
                        elif script.runAt == document_idle:
                            tag.string = userscript.wrapInEventListener("load", script.content)
                            soup.head.append(tag)
                        else:
                            tag.string = script.content
                            soup.body.append(tag)
                # Insert information comment:
                index: Optional[int] = indexOfDoctype(soup)
                soup.insert(0 if index is None else 1+index, Comment(
                    INFO_COMMENT_PREFIX + (
                        "No matching userscripts for this URL." if insertedScripts == []
                        else "These scripts were inserted:\n" + itemList(insertedScripts)
                    ) + "\n"
                ))
                # Keep character encoding:
                match_charset: Optional[Match] = REGEX_CHARSET.search(contentType)
                charset: str = CHARSET_DEFAULT if match_charset is None else match_charset.group(1)
                flow.response.content = str(soup).encode(charset)


def start():
    return UserscriptInjector()
