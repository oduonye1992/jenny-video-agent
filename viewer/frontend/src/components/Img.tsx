import { type ImgHTMLAttributes } from "react"

/** Img with lazy loading + async decode baked in. Drop-in replacement for <img>. */
export function Img(props: ImgHTMLAttributes<HTMLImageElement>) {
  return <img loading="lazy" decoding="async" {...props} />
}
