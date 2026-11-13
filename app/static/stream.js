/* Decode newline-delimited JSON independently of rendering and request state. */
async function* readJsonEvents(body) {
  if (!body) throw new Error("The server returned no response stream. Please retry.");
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const {done, value} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      let newline;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        if (line.trim()) yield JSON.parse(line);
      }
      if (done) break;
    }
    if (buffer.trim()) yield JSON.parse(buffer);
  } finally {
    try { await reader.cancel(); }
    finally { reader.releaseLock(); }
  }
}
