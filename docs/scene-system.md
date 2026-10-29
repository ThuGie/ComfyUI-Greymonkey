# Building a complete scene

## New nodes

**Greymonkey Scene Settings** selects the exact location and time of day from searchable catalog dropdowns. Random leaves that property open for compatible seeded filling. Connect `scene_settings` to Prompt Generator's new optional `scene_settings` input. This works with configured subject chains and Random Scene, including landscapes/interiors/posters. Theme still constrains compatibility; it never silently replaces the selected location.

**Greymonkey Environment Detail** selects a category and compatible option from global details: lighting, weather, atmosphere, room/terrain details, composition and other global controls present in the catalog. Chain `environment_details` into another node's `previous_details`; connect the last to Scene Settings.environment_details. Use Scene Settings for the main location and time, Camera Style for capture, and Subject Detail for details belonging to a person. Unknown options, competing slots and excessive selections are rejected. The backend remains authoritative for environmental and location compatibility.

**Greymonkey Scene Placement** inserts an independently configured object into an existing subject scene. Connect Scene Subject.scene to `scene`, Scene Object.related_object to `object`, choose a placement and connect its scene output onward to another placement or Prompt Generator. Select relationship None on the placed Scene Object. Choose table, desk, floor, shelf, wall, foreground/background, left/right, or relative placement beside/behind/in front of a subject. target_subject is the one-based preceding entity position, including objects. Stable references prevent later insertions from redirecting an earlier relationship.

## Typical connections

```text
Environment Detail -> Environment Detail -> Scene Settings -> Generator.scene_settings
Scene Subject -> Scene Placement -> Scene Placement -> Generator.scene
Scene Object A ----^                  ^
Scene Object B -----------------------|
Camera Style --------------------------------------> Generator.capture_settings
Generator.generation_result ------------------------> Save Image.generation_result
```

For example: select a home office location and daytime; add soft lighting in Environment Detail; configure a woman; place a laptop on a desk and a plant in the background. Every object has its own identity, colors, details and optional exact text. Objects contribute to the eight-entity limit; they do not increase the number of people described.

For **held/used objects**, keep the existing Scene Object.related_object -> Scene Subject.object_settings connection, with grip and Hold position on Scene Object. Then pass the person's scene through placement nodes for additional background objects. Do not connect the same object twice.

For **object-only scenes**, start with Scene Object.scene and add more objects through Scene Placement. For a **random scene**, Scene Settings applies directly; exact object placement currently requires a configured subject/object chain rather than an unresolved Random Scene recipe. This restriction produces a clear error instead of inventing targets or altering requested counts.

## Compatibility and persistence

Existing class IDs, output order, workflow connections and saved selections remain intact. Scene Settings is an optional generator input. New settings are saved by stable widget names using the existing frontend persistence system and are included in generation result metadata. Model switching preserves the cached resolved scene when these inputs are unchanged; changing settings regenerates the scene.

White background rejects explicit environment/location settings. Contradictory object positions must be corrected explicitly. Scene Placement retains existing object placement by default. Text, item colors and dimensions remain owned by their object. Catalog refresh updates location, time and environment dropdowns while retaining saved values.

Restart ComfyUI and refresh its page after installing. These nodes use the existing hosted location_id, time_id and global_detail_ids API fields; no additional website deployment is needed for the new scene-control nodes. Previously added text-object identities still require the supplied website data patch.

Implementation validation: Python/JavaScript syntax and prepared regression coverage only. No live requests, image generations or full test runs were performed for this update.
