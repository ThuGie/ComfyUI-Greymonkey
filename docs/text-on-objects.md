# Text on objects

Scene Object now has optional `display_text`, `text_placement`, `lettering`, `text_color`, `face_text_to_camera`, and `object_position` controls. Empty display_text preserves existing behavior. Text is stored in the owning object's scene details before generation, not appended to the finished prompt. Existing workflow settings and output types are unchanged.

## Person holding a message

1. Add **Greymonkey Scene Object**. Choose **A4 sheet of paper**, white, relationship **holding_two_handed**.
2. Set `display_text` to the exact words, for example `Hello, world!`. Select centered-on-front placement, black lettering and face_text_to_camera enabled.
3. Connect its `related_object` output to Scene Subject's `object_settings`. Keep the person's legacy Related Object and Relationship at None.
4. Connect Scene Subject to Prompt Generator. Choose a medium or wider camera framing that shows both hands and the paper.

## Object placed in the scene

Choose a sign, whiteboard or other object; set relationship **none** and choose object_position (for example on a table). Connect related_object to a person's object_settings to include it without a holding interaction. For an object-only picture, use Scene Object's `scene` output. Use previous_subjects to chain independent objects.

## Labels, covers and screens

Select the actual object identity, enter the exact text and choose on-the-label, screen, cover or side placement. Colors and properties remain owned by that object. One text block is supported per object; use independent objects for multiple messages. Literal text accepts Unicode, quotes and line breaks (maximum 1,000 characters); enter only words that should appear, not prompt instructions.

## Install and hosting

Restart ComfyUI after updating Python files, then refresh the frontend. The new controls work with the existing hosted API for existing identities. New paper/card/poster/sign/whiteboard identities require uploading `options/v4/nodes/expanded/text-surfaces.json` into the website's v4.1 deployment, then refreshing the node catalog. The supplied website patch ZIP contains that relative path. The node update does not deploy the website automatically.

The submitted recipe, submitted request and resolved scene carry the text in object details. Connect generation_result to Save Image to retain it. Models still vary in text rendering accuracy; prompts cannot guarantee exact lettering.
