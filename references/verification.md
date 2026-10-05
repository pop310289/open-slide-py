# Verification

## Every output

- `python3 -m open_slide_py validate deck.json` prints every error and warning as JSON and exits with 1 when there are errors. Errors must be zero; handle each warning (text overflow, overlapping text, low contrast, small sentences, sentences repeated across slides, images without alternative text), and mark deliberate exceptions with `ignore_warnings` and explain them in the report. Warnings are estimates; the real rendering still has the last word.
- Compare the text, numbers, units, notes and links slide by slide.
- Look at whole slides and details at the real rendering size, and record overflow, clipping, how labels match figures, and whether sources and footnotes are legible. Structural tests do not stand for visual quality.
- For the interactive HTML, use the keyboard, toolbar, touch and swipes, step mode, the slide list, notes and the timer. Check that it works offline, that the CSP reports no errors, and that the content is complete with JavaScript disabled and when printed. Label desktop, phone and emulator checks separately, and do not carry over the static version's no-JavaScript result.
- Only editing text and object positions in Office or Keynote, saving a PPTX, reopening it and finding the changes intact counts as an editing round trip. Record the app and OS, the SHA-256 of the input and output, the steps and the rendering evidence. Opening the file alone is not a round trip.
- Check fonts separately as OOXML declarations, what the operating system actually resolves, and what the output renders or embeds in a PDF. Without a test on Windows, say it is unverified; a theme declaration is not cross-platform fidelity.

Once the output or the source changes, older hashes, screenshots and round-trip results are history only. Deliver the source JSON, the assets, the requested outputs and a check summary that matches the version; the examples bundled with this skill do not vouch for a new project.
