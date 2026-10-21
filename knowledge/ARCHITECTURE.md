# MCBH Professional Architect — Geometry, Knowledge & Quality Protocol

## Not a house prefab engine

The MCP agent must act as a lead architect and Minecraft builder. It interprets the user's actual request, biome, era, use, scale, surrounding architecture, ground survey and image references. The \`mcbh_design_build\` tool is an **original geometric baseline** for houses, taverns, workshops, libraries and watchtowers; it is not a language model and is not capable of solving every architectural idea automatically. For unconventional structures (castles, ships, bridges, organic fantasy or sculpted terrain) the agent **must plan explicit geometry** via the existing \`mcbh_stage_blueprint\` / \`mcbh_validate_blueprint\` tools, not mislabel a house as a castle.

## Professional agent workflow (mandatory)

1. **Observe first.** Read \`mcbh_read_skill('all')\`, \`mcbh_visual_guides\` and \`mcbh://architect\`. Inspect external reference images with host vision support and record concrete architectural features, materials and proportions. If images are unavailable, disclose this.
2. **Survey the exact site** using \`mcbh_survey_terrain\` at four corners, centre, entrance, future pathway and adjoining land. Convert absolute sampled coordinates to the design-local \`[x,z,surface_y]\` array. Check dimension, water, obstacles, neighboring builds and skyline via external screenshots. RCON cannot infer these from height alone.
3. **Define a design program**: intended building use; 2–4 story reasons; mandatory rooms; primary/secondary masses; public/private circulation; width/depth/floor count; biome-specific climate adaptation; material hierarchy; focal facade; story of the building. Plan in **blocks** using ratios and scale, not vague adjectives.
4. **Mass studies before detail:** create 2 or 3 alternative rough mass arrangements. For a bounded cottage/inn, vary seed, dimensions, wing and storeys via \`mcbh_design_build\`. For other typologies, write a custom phased blueprint. Compare each from north/south/east/west at 30+ blocks distance. Only then choose one design.
5. **Architectural structure:** corner posts and structural rhythm, inset infill plane, real voids at openings, window sills + lintels, shadow-producing eaves, roof seams, stepped foundation adapting to terrain, accessible entrances, covered stairs and believable loading.
6. **Block palette discipline:** choose roles (main 60–75%, structural 15–25%, details 5–12%, accents under 5%) as elastic targets. Compare actual block faces in game, not SVG approximations. Prefer gradient *regions* according to age, runoff and weather, not random checkerboard. Avoid overdetailing small facades.
7. **Roof construction:** reserve actual stair-facing/half states, build ridge first in geometry, resolve intersecting roofs and valleys, build dormers only if they physically meet the main roof, no floating pieces. Flat modern/adobe roofs require parapet/coping and believable drainage.
8. **Interior as part of the architecture:** plan room zoning and functional work surfaces, door clearances, circulation, staircase headroom, ceiling clearances, windows looking into real rooms, floor supports, lighting and obtainable Survival materials. Don't furnish merely as scattered barrels.
9. **Terrain integration:** avoid blind flattening and mass air-clearing. Anchors are world Y (floor), survey provides surface Y; use pier foundations and retaining walls where heights change, place paths to real doors, group vegetation naturally. For slopes higher than the floor, redesign rather than overwrite blindly.
10. **Critique loop:** \`mcbh_export_viewer\` provides an approximate isometric viewer (colors are not real Minecraft textures). Seek actual in-game screenshots from front/back/sides/roof and inside each room; log errors by severity. \`mcbh_architecture_review\` checks mechanical invariants, NOT artistry. Use \`mcbh_refine_design\` to create a preserved new generation or author more custom geometry. Repeat until approved.
11. **Approve and build:** keep the original snapshot and a world backup. Inspect exact preview, material totals and affected bounds. Explicit human permission is required before \`mcbh_execute_phase\`. Build a phase at a time and pause if server behavior is ambiguous. Do NOT declare done only because CI or RCON succeeded.

## Built-in baseline: when to use it

Use \`mcbh_architect_capabilities\` and then \`mcbh_design_build\` with a structured brief. Support:
- Styles: medieval_timber, alpine_rustic, japanese_traditional, modern_concrete, desert_adobe, dark_fantasy.
- Uses: house, tavern, workshop, library, watchtower.
- 13–39 block width/depth; 1–3 floors; site anchor and up to 36 height samples.
- Vary the seed to obtain a different balcony, wing, chimney, vegetation, division or palette arrangement. This is controlled procedural variation, not original image reasoning.
- The output has a reusable structure ID so \`mcbh_structure_layer\`, \`mcbh_structure_steps\`, \`mcbh_structure_materials\`, \`mcbh_export_viewer\` and \`mcbh_export_mcfunction\` all remain functional.
- The output also has a staged job, preserving site/foundation/structure/roof/facade/interior/landscape/lighting phases, and a guarded RCON workflow.

## Visual acceptance checklist

Do not claim “professional” without human/vision verification of every criterion:

- Silhouette: multiple readable masses, a meaningful focal point, no boring shoebox.
- Facade: actual stepped depth and window recess; corner resolution; no structural breaks.
- Roof: correct ridge, overhangs, gable joins, no stair orientation artifacts.
- Palette: functional roles and texture coherence, no random block soup.
- Terrain: believable retaining, grading, stairs, path to the door and planting.
- Interior: real access to each function, stairs traversable, useful furniture, lighting.
- Lifecycle: all phases built in order, no accidental destruction, correct version and blocks.
- Photography: screenshots inspected at 4 exteriors, from above and inhabited interiors, both day/night if lighting matters.

### Explicit limitations

MCBH uses Java commands over RCON and does **not** capture game screenshots, read full blocks or detect all world collisions. The built-in procedural architect covers small-to-medium buildings and needs human/agent visual refinement. MCBH does not embed a trained Minecraft generative AI model or proprietary Brictora code. It cannot guarantee a human-level outcome without visual review and iteration.
