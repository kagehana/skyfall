# Item API — `LuaItem`

A `LuaItem` is a backpack or equipped item. You get them from the inventory
methods:

```lua
local client = clients()[1]

for _, it in ipairs(client:backpack()) do
    print(it:name(), it:school(), it:object_type())
end

local hat = client:find_equipped("Hat")
if hat then print(hat:name(), hat:adjective_list()) end
```

`info()` returns every field in a single memory pass as a table — cheaper than
calling each accessor separately when you need several fields:

```lua
local it = client:find_item("Mega Snack")
if it then
    local i = it:info()
    print(i.name, i.template_id, i.description)
end
```

---

## Full method reference

<!-- AUTOGEN:LuaItem START — generated from source; do not edit. Run: python -m src.lang.docgen --emit -->
#### Identity

| Method | Signature | Description |
|---|---|---|
| `name` | `() -> str` | Item display name |
| `debug_name` | `() -> str` | Debug name string |
| `template_id` | `() -> int` | Template id |
| `global_id` | `() -> int` | Per-session global id |
| `perm_id` | `() -> int` | Permanent id |
| `object_type` | `() -> str` | Item object-type string |
| `school` | `() -> str` | Item's school requirement/affinity |

#### Details

| Method | Signature | Description |
|---|---|---|
| `description` | `() -> str` | Item description / flavor text |
| `adjective_list` | `() -> str` | Raw adjective list string (stat modifiers) |
| `icon` | `() -> str` | Icon asset path |
| `is_equipped` | `() -> bool` | True if the item is currently equipped |
| `info` | `()` | All fields in one memory pass as a table |
<!-- AUTOGEN:LuaItem END -->
