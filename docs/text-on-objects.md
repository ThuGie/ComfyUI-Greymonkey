# Text on objects

Scene Object now has optional `display_text`, `text_placement`, `lettering`, `text_color`, `face_text_to_camera`, `object_position`, `hold_position` and `object_orientation` controls. Empty display_text preserves existing behavior. Text is stored in the owning object's scene details before generation, not appended to the finished prompt. Existing workflow settings and output types are unchanged.

## Person holding a message

1. Add **Greymonkey Scene Object**. Choose **A4 sheet of paper**, white, relationship **holding_two_handed**.
2. Set `hold_position` (for example **at chest height** or **above the head**) independently of the grip. Set `object_orientation` to portrait, landscape or a slight tilt. Set `display_text` to the exact words, for example `Hello, world!`. Select centered-on-front placement, black lettering and face_text_to_camera enabled.
3. Connect its `related_object` output to Scene Subject's `object_settings`. Keep the person's legacy Related Object and Relationship at None.
4. Connect Scene Subject to Prompt Generator. Choose a medium or wider camera framing that shows both hands and the paper.

## Object placed in the scene

Choose a sign, whiteboard or other object; set relationship **none** and choose object_position (for example on a table). Connect related_object to a person's object_settings to include it without a holding interaction. For an object-only picture, use Scene Object's `scene` output. Use previous_subjects to chain independent objects.

## Labels, covers and screens

Select the actual object identity, enter the exact text and choose on-the-label, screen, cover or side placement. Colors and properties remain owned by that object. One text block is supported per object; use independent objects for multiple messages. Literal text accepts Unicode, quotes and line breaks (maximum 1,000 characters); enter only words that should appear, not prompt instructions.

## Install and hosting

Restart ComfyUI after updating Python files, then refresh the frontend. The new controls work with the existing hosted API for existing identities. New identities require uploading all three files from the website patch, preserving paths: `options/v4/nodes/expanded/text-surfaces.json`, `options/v4/config/menu-taxonomy.json`, and `lib/PublicApi.php`. The taxonomy file is required for graph loading; PublicApi exposes the correct material defaults. Then refresh the node catalog. The node update does not deploy the website automatically.

The submitted recipe, submitted request and resolved scene carry the text in object details. Connect generation_result to Save Image to retain it. Models still vary in text rendering accuracy; prompts cannot guarantee exact lettering.

## Holding versus placing

- Relationship controls the grip: holding_two_handed, holding_left_hand, holding_right_hand, holding_delicately or holding_on_palm.
- Hold position controls where: chest, waist, stomach, shoulders, eye level, below the chin, beside/in front of the face, above the head, beside the hip, in front of thighs, on the lap, toward the camera or out to either side.
- Object orientation controls rotation. Face text to camera independently controls whether its readable face is directed toward the viewpoint.
- Object position is for placed objects (desk, table, wall, shelf etc.). Leave it unspecified when holding an object. Conflicting explicit settings produce an error, rather than silently overriding each other.
- Existing relationship choices such as holding_at_chest still work. To choose a different height, use a grip without a fixed height and set Hold position.
- Choose framing that includes the requested location. A close-up of the face cannot show an object at hip level.

## Expanded text surfaces

37 explicit surfaces include paper, message cards, posters, signs, whiteboards, clipboards, certificates, letters, envelopes, postcards, greeting/business cards, closed/open notebooks, menus, newspapers, magazine covers, chalkboards, placards, banners, pennants, gift/shipping boxes, shopping/tote bags, folded printed T-shirts, held-up jerseys, badges, luggage tags, stickers, product label cards, labeled bottles/cans, message phones/tablets, lightboxes and balloons.

Clothing objects here are held/displayed items; these choices do not put the item onto the person's body. Existing object identities also accept display_text. Each text-specific identity is explicitly selectable but excluded from automatic random fill so it does not crowd ordinary random scenes.

## Physical size and framing

A4 now specifies 21 × 29.7 cm. For a smaller message use Postcard or Handheld message card (15 × 10 cm), Greeting card (10.5 × 14.8 cm), Business card (8.5 × 5.5 cm), or Name badge (9 × 6 cm). These dimensions are descriptive constraints, not guaranteed geometry. Short text and medium/three-quarter framing balance a small item with readable lettering; full-body shots leave fewer pixels for small text. Hold position remains independent of item size.
