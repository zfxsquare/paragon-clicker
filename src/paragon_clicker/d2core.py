from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ENV = "diablocore-4gkv4qjs9c6a0b40"
APP_SIGN = "diablocore"
APP_ACCESS_KEY_ID = 1
APP_ACCESS_KEY = "ed6fe96e6ca08acf392d360094a58477"
PARAGON_VERSION = "71566"
PARAGON_LOCALE = "zhCN"
PARAGON_REVISION = "26"
GRID_SIZE = 21
NODE_NUM = 21
DELTAS = [(-1, 0), (0, -1), (0, 1), (1, 0)]
SAFE_EXPR = re.compile(r"^[0-9+*\- /().A-Za-z]+$")


def parse_planner_input(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("Planner URL is empty")

    if re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return text

    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Invalid planner URL")

    query = parse_qs(parsed.query)
    bd_list = query.get("bd")
    if not bd_list or not bd_list[0].strip():
        raise ValueError("Planner URL does not contain bd=")
    return bd_list[0].strip()


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def create_sign(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = base64url(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    encoded_payload = base64url(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    message = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{base64url(signature)}"


def fetch_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> Any:
    request = Request(url, method=method, headers=headers or {}, data=body)
    with urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def invoke_cloud_function(
    function_name: str, request_data: dict[str, Any]
) -> dict[str, Any]:
    import time

    timestamp = int(time.time() * 1000)
    sign = create_sign(
        {
            "data": {},
            "timestamp": timestamp,
            "appAccessKeyId": APP_ACCESS_KEY_ID,
            "appSign": APP_SIGN,
        },
        APP_ACCESS_KEY,
    )

    payload = {
        "action": "functions.invokeFunction",
        "dataVersion": "2020-01-10",
        "env": ENV,
        "function_name": function_name,
        "request_data": json.dumps(request_data, ensure_ascii=False),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "content-type": "application/json;charset=UTF-8",
        "X-TCB-App-Source": f"timestamp={timestamp};appAccessKeyId={APP_ACCESS_KEY_ID};appSign={APP_SIGN};sign={sign}",
        "x-seqid": hashlib.md5(body).hexdigest()[:16],
        "X-SDK-Version": "@cloudbase/js-sdk/python-local",
    }
    response = fetch_json(
        f"https://tcb-api.tencentcloudapi.com/web?env={ENV}",
        method="POST",
        headers=headers,
        body=body,
    )
    response_data = response.get("data", {}).get("response_data")
    if not response_data:
        raise ValueError(f"Cloud function returned invalid response: {response}")
    return json.loads(response_data)


def query_plan(bd: str) -> dict[str, Any]:
    return invoke_cloud_function(
        "function-planner-queryplan", {"bd": bd, "enableVariant": True}
    )


@lru_cache(maxsize=4)
def fetch_paragon_db(
    version: str = PARAGON_VERSION, locale: str = PARAGON_LOCALE
) -> dict[str, Any]:
    url = f"https://cloudstorage.d2core.com/data/d4/{version}/paragon_{locale}.json?env=prod&v={PARAGON_REVISION}"
    return fetch_json(url)


def parse_node_key(node_key: str) -> tuple[int, int, str]:
    parts = node_key.split("_")
    return int(parts[0]), int(parts[1]), "_".join(parts[2:])


def get_rotated_pos(row: int, col: int, rotate: int) -> dict[str, int]:
    next_row = row
    next_col = col
    for _ in range(rotate):
        previous_row = next_row
        next_row = next_col
        next_col = NODE_NUM - 1 - previous_row
    return {"row": next_row, "col": next_col}


def get_connect_board_pos(x: int, y: int, row: int, col: int) -> dict[str, int]:
    dx = 0
    dy = 0
    next_row = 0
    next_col = 0
    if row == 0:
        dy = -1
        next_row = NODE_NUM - 1
        next_col = col
    elif row == NODE_NUM - 1:
        dy = 1
        next_row = 0
        next_col = col
    elif col == 0:
        dx = -1
        next_row = row
        next_col = NODE_NUM - 1
    elif col == NODE_NUM - 1:
        dx = 1
        next_row = row
        next_col = 0
    return {"x": x + dx, "y": y + dy, "row": next_row, "col": next_col}


def get_connect_path_with_order(
    spent_map: dict[str, Any],
) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    rotated_boards: dict[str, list[list[str | None]]] = {}
    visited: dict[str, dict[str, bool]] = {}
    queue: list[dict[str, Any]] = []
    order: list[dict[str, str]] = []

    for board_key, board_state in spent_map.items():
        visited[board_key] = {}
        rotated_boards[board_key] = [
            [None for _ in range(NODE_NUM)] for _ in range(NODE_NUM)
        ]
        for node_key in board_state.get("data", []):
            row, col, _ = parse_node_key(node_key)
            rotated = get_rotated_pos(row, col, int(board_state.get("rotate", 0)))
            rotated_boards[board_key][rotated["row"]][rotated["col"]] = node_key
            if "StartNode" in node_key:
                visited[board_key][node_key] = True
                queue.append(
                    {
                        "board": board_key,
                        "key": node_key,
                        "row": rotated["row"],
                        "col": rotated["col"],
                    }
                )
                order.append({"board": board_key, "key": node_key})

    while queue:
        current = queue.pop(0)
        for dy, dx in DELTAS:
            next_row = current["row"] + dy
            next_col = current["col"] + dx
            next_board = current["board"]
            next_key = None
            if 0 <= next_row < NODE_NUM and 0 <= next_col < NODE_NUM:
                next_key = rotated_boards[next_board][next_row][next_col]

            if next_key is None and "Generic_Gate" in current["key"]:
                board_state = spent_map[current["board"]]
                linked = get_connect_board_pos(
                    int(board_state.get("x", 0)),
                    int(board_state.get("y", 0)),
                    current["row"],
                    current["col"],
                )
                for candidate_key, candidate_state in spent_map.items():
                    if (
                        int(candidate_state.get("x", 0)) == linked["x"]
                        and int(candidate_state.get("y", 0)) == linked["y"]
                    ):
                        next_board = candidate_key
                        next_row = linked["row"]
                        next_col = linked["col"]
                        next_key = rotated_boards[next_board][next_row][next_col]
                        break

            if next_key and not visited[next_board].get(next_key):
                visited[next_board][next_key] = True
                queue.append(
                    {
                        "board": next_board,
                        "key": next_key,
                        "row": next_row,
                        "col": next_col,
                    }
                )
                order.append({"board": next_board, "key": next_key})

    connect_path = {
        board_key: list(nodes.keys()) for board_key, nodes in visited.items()
    }
    return connect_path, order


def get_node_kind(node_id: str) -> str:
    if "StartNode" in node_id:
        return "start"
    if node_id == "Generic_Gate":
        return "gate"
    if node_id == "Generic_Socket":
        return "socket"
    parts = node_id.split("_")
    return (parts[1] if len(parts) > 1 else "normal").lower()


def get_node_definition(
    paragon_db: dict[str, Any], char: str, node_id: str
) -> dict[str, Any] | None:
    return paragon_db.get("Generic", {}).get("node", {}).get(node_id) or paragon_db.get(
        char, {}
    ).get("node", {}).get(node_id)


def resolve_thresholds(
    node_def: dict[str, Any] | None, char: str, board_index: int
) -> list[dict[str, Any]]:
    if not node_def:
        return []
    requirements = node_def.get("threshold_requirements", {}).get(char)
    if not requirements:
        return []

    resolved: list[dict[str, Any]] = []
    for requirement in requirements:
        raw = str(requirement.get("value", ""))
        value: int | float | None = None
        if SAFE_EXPR.fullmatch(raw) and "ParagonBoardEquipIndex" in raw:
            expr = raw.replace("ParagonBoardEquipIndex", str(board_index))
            value = eval(expr, {"__builtins__": {}}, {})
        elif re.fullmatch(r"^[0-9.+\-]+$", raw):
            value = float(raw) if "." in raw else int(raw)
        resolved.append(
            {"name": requirement.get("name"), "raw": raw, "resolved": value}
        )
    return resolved


def fallback_node_name(node_id: str) -> str:
    return node_id.replace("_", " ")


def build_variant_boards(
    variant: dict[str, Any], char: str, paragon_db: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    spent_map = variant.get("paragon") or {}
    connect_path, order = get_connect_path_with_order(spent_map)
    order_map = {
        f"{item['board']}:{item['key']}": index for index, item in enumerate(order)
    }
    board_keys = sorted(
        spent_map.keys(), key=lambda key: int(spent_map[key].get("index", 0))
    )
    boards: list[dict[str, Any]] = []

    for board_key in board_keys:
        board_state = spent_map[board_key]
        board_name = (
            paragon_db.get(char, {})
            .get("board", {})
            .get(board_key, {})
            .get("name", board_key)
        )
        selected_nodes: list[dict[str, Any]] = []

        for node_key in board_state.get("data", []):
            row, col, node_id = parse_node_key(node_key)
            node_def = get_node_definition(paragon_db, char, node_id)
            selected_nodes.append(
                {
                    "key": node_key,
                    "nodeId": node_id,
                    "row": row,
                    "col": col,
                    "rotated": get_rotated_pos(
                        row, col, int(board_state.get("rotate", 0))
                    ),
                    "kind": get_node_kind(node_id),
                    "name": (node_def or {}).get("name") or fallback_node_name(node_id),
                    "desc": (node_def or {}).get("desc"),
                    "connected": node_key in connect_path.get(board_key, []),
                    "pointOrder": order_map.get(f"{board_key}:{node_key}"),
                    "glyph": (board_state.get("glyph") or {}).get(node_key),
                    "glyphRank": (board_state.get("glyphRank") or {}).get(node_key),
                    "thresholds": resolve_thresholds(
                        node_def, char, int(board_state.get("index", 0))
                    ),
                    "attributes": (node_def or {}).get("attributes", []),
                }
            )

        selected_nodes.sort(key=lambda item: item.get("pointOrder", 10**9))
        boards.append(
            {
                "boardKey": board_key,
                "boardName": board_name,
                "index": int(board_state.get("index", 0)),
                "rotate": int(board_state.get("rotate", 0)),
                "parent": board_state.get("parent"),
                "position": {
                    "x": int(board_state.get("x", 0)),
                    "y": int(board_state.get("y", 0)),
                },
                "selectedNodes": selected_nodes,
            }
        )
    return boards, order


def get_selected_cells(board: dict[str, Any]) -> list[dict[str, Any]]:
    return list(board.get("selectedNodes", []))


def get_parent_entry_edge(
    board: dict[str, Any], boards_by_key: dict[str, dict[str, Any]]
) -> dict[str, int | None] | None:
    parent_key = board.get("parent")
    if not parent_key:
        return None
    parent = boards_by_key.get(parent_key)
    if not parent:
        return None
    dx = int(board["position"]["x"]) - int(parent["position"]["x"])
    dy = int(board["position"]["y"]) - int(parent["position"]["y"])
    if dy == -1:
        return {"row": NODE_NUM - 1, "col": None}
    if dy == 1:
        return {"row": 0, "col": None}
    if dx == -1:
        return {"row": None, "col": NODE_NUM - 1}
    if dx == 1:
        return {"row": None, "col": 0}
    return None


def is_cell_on_edge(cell: dict[str, Any], edge: dict[str, int | None] | None) -> bool:
    if not edge:
        return False
    if edge.get("row") is not None:
        return int(cell["rotated"]["row"]) == int(edge["row"])
    if edge.get("col") is not None:
        return int(cell["rotated"]["col"]) == int(edge["col"])
    return False


def get_board_entry_cells(
    board: dict[str, Any], boards_by_key: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    selected_cells = get_selected_cells(board)
    if not board.get("parent"):
        starts = [cell for cell in selected_cells if cell.get("kind") == "start"]
        if starts:
            return starts
    parent_edge = get_parent_entry_edge(board, boards_by_key)
    parent_gates = [
        cell
        for cell in selected_cells
        if cell.get("kind") == "gate" and is_cell_on_edge(cell, parent_edge)
    ]
    if parent_gates:
        return parent_gates
    any_gates = [cell for cell in selected_cells if cell.get("kind") == "gate"]
    if any_gates:
        return any_gates
    return selected_cells[:1]


def build_board_local_cells(
    board: dict[str, Any], boards_by_key: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_cells = get_selected_cells(board)
    selected_map = {
        f"{cell['rotated']['row']}:{cell['rotated']['col']}": cell
        for cell in selected_cells
    }
    visited: set[str] = set()
    queue: list[dict[str, Any]] = []
    result: list[dict[str, Any]] = []

    def enqueue(cell: dict[str, Any] | None) -> None:
        if not cell:
            return
        if cell["key"] in visited:
            return
        visited.add(cell["key"])
        queue.append(cell)

    entry_cells = get_board_entry_cells(board, boards_by_key)
    for cell in entry_cells:
        enqueue(cell)

    while len(visited) < len(selected_cells):
        while queue:
            current = queue.pop(0)
            result.append(current)
            for dy, dx in DELTAS:
                neighbor = selected_map.get(
                    f"{current['rotated']['row'] + dy}:{current['rotated']['col'] + dx}"
                )
                enqueue(neighbor)
        next_seed = next(
            (cell for cell in selected_cells if cell["key"] not in visited), None
        )
        enqueue(next_seed)
    return entry_cells, result


def build_step(
    board: dict[str, Any],
    cell: dict[str, Any],
    step: int,
    local_step: int | None,
    glyphs: dict[str, Any],
) -> dict[str, Any]:
    glyph = None
    if cell.get("glyph"):
        glyph = {
            "key": cell["glyph"],
            "name": glyphs.get(cell["glyph"], {}).get("name"),
            "rank": cell.get("glyphRank") or 0,
        }
    return {
        "step": step,
        "localStep": local_step,
        "action": "click_node",
        "boardKey": board["boardKey"],
        "boardName": board["boardName"],
        "boardIndex": board["index"],
        "boardPosition": board["position"],
        "boardRotate": board["rotate"],
        "parentBoardKey": board.get("parent"),
        "nodeKey": cell["key"],
        "nodeId": cell["nodeId"],
        "nodeName": cell["name"],
        "nodeKind": cell["kind"],
        "rawCoord": {"row": cell["row"], "col": cell["col"]},
        "rotatedCoord": cell["rotated"],
        "connected": bool(cell.get("connected")),
        "glyph": glyph,
        "thresholds": cell.get("thresholds", []),
        "attributes": cell.get("attributes", []),
    }


def build_board_order(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    order: list[dict[str, Any]] = []
    for step in steps:
        if step["boardKey"] in seen:
            continue
        seen.add(step["boardKey"])
        order.append(
            {
                "order": len(order) + 1,
                "boardKey": step["boardKey"],
                "boardName": step["boardName"],
                "boardIndex": step["boardIndex"],
                "boardPosition": step["boardPosition"],
                "boardRotate": step["boardRotate"],
                "parentBoardKey": step["parentBoardKey"],
                "firstStep": step["step"],
            }
        )
    return order


def build_board_flow(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for step in steps:
        current = groups[-1] if groups else None
        if current is None or current["boardKey"] != step["boardKey"]:
            groups.append(
                {
                    "segment": len(groups) + 1,
                    "boardKey": step["boardKey"],
                    "boardName": step["boardName"],
                    "boardIndex": step["boardIndex"],
                    "boardPosition": step["boardPosition"],
                    "boardRotate": step["boardRotate"],
                    "parentBoardKey": step["parentBoardKey"],
                    "firstStep": step["step"],
                    "lastStep": step["step"],
                    "clickCount": 1,
                }
            )
            continue
        current["lastStep"] = step["step"]
        current["clickCount"] += 1
    return groups


def build_variant_sequence(
    root_data: dict[str, Any], variant: dict[str, Any], paragon_db: dict[str, Any]
) -> dict[str, Any]:
    char = root_data.get("char") or variant.get("char")
    if not char:
        raise ValueError("Missing character type in build data")

    boards, global_order = build_variant_boards(variant, char, paragon_db)
    boards_by_key = {board["boardKey"]: board for board in boards}
    glyphs = paragon_db.get(char, {}).get("glyph", {})

    global_steps: list[dict[str, Any]] = []
    for index, point in enumerate(global_order, start=1):
        board = boards_by_key[point["board"]]
        cell = next(
            cell for cell in board["selectedNodes"] if cell["key"] == point["key"]
        )
        global_steps.append(build_step(board, cell, index, None, glyphs))

    step_counter = 1
    board_sequences: list[dict[str, Any]] = []
    for board_sequence_index, board in enumerate(
        sorted(boards, key=lambda item: item["index"]), start=1
    ):
        entry_cells, cells = build_board_local_cells(board, boards_by_key)
        steps: list[dict[str, Any]] = []
        for local_index, cell in enumerate(cells, start=1):
            steps.append(build_step(board, cell, step_counter, local_index, glyphs))
            step_counter += 1

        board_sequences.append(
            {
                "boardSequenceIndex": board_sequence_index,
                "boardKey": board["boardKey"],
                "boardName": board["boardName"],
                "boardIndex": board["index"],
                "boardPosition": board["position"],
                "boardRotate": board["rotate"],
                "parentBoardKey": board.get("parent"),
                "clickCount": len(steps),
                "entryNodes": [
                    {
                        "nodeKey": cell["key"],
                        "nodeName": cell["name"],
                        "nodeKind": cell["kind"],
                        "rawCoord": {"row": cell["row"], "col": cell["col"]},
                        "rotatedCoord": cell["rotated"],
                    }
                    for cell in entry_cells
                ],
                "steps": steps,
            }
        )

    steps = [step for sequence in board_sequences for step in sequence["steps"]]
    return {
        "meta": {
            "title": root_data.get("title"),
            "char": char,
            "season": root_data.get("season"),
            "variantIndex": variant.get("variantIndex", 0),
            "variantName": variant.get("name"),
            "boardCount": len(boards),
            "pointCount": len(global_steps),
        },
        "mode": "board_by_board",
        "boardOrder": build_board_order(steps),
        "boardSequences": board_sequences,
        "steps": steps,
        "globalBoardFlow": build_board_flow(global_steps),
        "globalSteps": global_steps,
        "notes": [
            "steps is the recommended board-by-board click order without board switching automation.",
            "boardSequences contains the per-board click list after you manually switch to that board.",
            "The selected screen rectangle is divided into 21x21 cells and the program clicks the center of each target cell.",
        ],
    }


def build_sequence_from_planner_input(planner_input: str) -> dict[str, Any]:
    bd = parse_planner_input(planner_input)
    response = query_plan(bd)
    root_data = response.get("data")
    if not root_data:
        raise ValueError("Planner response does not contain data")

    variant_list = root_data.get("variants") or [root_data]
    paragon_db = fetch_paragon_db()

    sequences = []
    for index, variant in enumerate(variant_list):
        tagged_variant = dict(variant)
        tagged_variant["variantIndex"] = index
        sequences.append(build_variant_sequence(root_data, tagged_variant, paragon_db))

    return {
        "meta": {
            "bd": bd,
            "title": root_data.get("title"),
            "char": root_data.get("char"),
            "season": root_data.get("season"),
            "variantCount": len(sequences),
        },
        "variants": sequences,
    }
