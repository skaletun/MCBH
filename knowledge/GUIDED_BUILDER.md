# MCBH — Guided Builder, public Brictora workflow study

Research date: 2026-10-21.

This is an **independently implemented, offline-first** build guide, not a copy of Brictora source, images, designs, endpoints or commercial data. Based on the observed public UI and published site descriptions:

- Brictora exposes upload of `.schem` and `.litematic` structures, not text-to-new-building generation. It turns existing voxel models into construction instructions.
- The public viewer offers Survival / Creative choices, step-by-step blocks grouped by material and quantity, a material checklist, progress slider and step focus, rotated 3D view, dimension markers, grid/wireframe colors and preview mode.
- A layer-by-layer reading mode, measurements and some editing tools are shown in premium UI. MCBH's independent design makes its own layer and measurement features local and unmetered.
- Some original-site account features (creator profiles, uploads to Brictora, payments, likes, follows) are outside MCBH scope, which is a local agent and Minecraft-build MCP rather than a social web platform.

## User and agent workflow

1. Place a legally owned or permitted `.schem` / `.litematic` in `$MCBH_IMPORT_DIR` (default `~/.mcbh/imports/`). Only plain file names allowed: no URL fetching and no arbitrary filesystem paths.
2. Call `mcbh_import_structure(filename)`; inspect dimensions, regions, warnings, air handling and exact material list.
3. Call `mcbh_structure_materials(structure_id, 'survival')` for exact item counts, stacks and remainders. Do **not** claim recipe data unless the target version and actual registry are verified.
4. Call `mcbh_structure_steps` page by page: output is bottom-up in increasing world Y, grouped as same material on adjacent X positions, with exact coordinate runs. This is a deterministic assembly order, not an unsupported claim of optimal human assembly order; when sand, redstone, fluids or wall-attached decorations are involved, explicitly check support/dependencies.
5. Call `mcbh_structure_layer` with crop offsets and a Y coordinate for an exact top-down symbol map. Use `mcbh_structure_summary` for per-height totals and footprint.
6. For an interactive local display, call `mcbh_export_viewer` and open the returned `.html` file (if supported by host); orbit, toggle layer, view steps, track progress, inspect material checklist and measurements. Visualization uses approximate palette colors, **not true Mojang textures**.
7. To place an imported build in Minecraft: `mcbh_stage_structure(id,[x,y,z])` → `mcbh_preview(job)` → explain destruction risk & request **explicit human approval** → repeated `mcbh_execute_phase` in safe batches. Alternatively create a datapack function with `mcbh_export_mcfunction`. `clear_air` is **off** by default. Surface and collision checks cannot be inferred from a file alone.
8. Separately use the original human-professional builder skill to **design a unique new structure**. It is not interchangeable with reconstructing an imported schematic.

## Format assumptions and important limits

- Sponge `.schem` supports VarInt palette BlockData (v2) or nested Blocks.Data (v3), with X-fastest ordering.
- Litematic supports multiple regions, signed region dimensions, full block states, packed bit arrays spanning long boundaries and deterministic overlap precedence. Region tile/entity metadata is not reconstructed.
- Files are size limited (16 MiB stored; 64 MiB inflated, 500k covered positions, max 250k non-air). This is a safety/budget constraint, not a technical Minecraft limitation.
- Block entities and entities are skipped with warnings; chests lose inventories, signs lose text, decorative entities are not reproduced. Waterlogging physics, leaf updates, scaffolding and all other world interactions need server-side verification.
- For each layer, the returned coordinate grid is exact and includes a legend; colors and renderer perspective are instructional approximations.
- Material counts are derived from included non-air blocks, not from the output of /fill after in-world collisions or replace filters.
- REA research approach: `morluto/rea` documents `list-browser-targets`, `inspect-web-page`, `analyze-web-bundle`, `observe-web-session`, and `capture-web-screenshot` via local Chromium CDP. These capabilities **were not run here**; the analysis used REA's official docs plus an independent live public-browser interaction. There is no claim to the service's internal algorithms, source code, network payloads or private data.

Source links:
- https://brictora.build/
- https://brictora.build/legal/terms
- https://github.com/morluto/rea
- https://github.com/morluto/rea/blob/main/docs/browser-observation.md
- https://github.com/SpongePowered/Schematic-Specification
- https://github.com/maruohon/litematica
