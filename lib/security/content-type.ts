const APPLICATION_JSON_SUFFIX = /^application\/[a-z0-9!#$&^_.+-]+\+json$/;

/** Parses only the media type token; parameters such as charset are ignored. */
export function isJsonContentType(value: string | null): boolean {
  const mediaType = value?.split(";", 1)[0].trim().toLowerCase() ?? "";
  return mediaType === "application/json" || APPLICATION_JSON_SUFFIX.test(mediaType);
}
