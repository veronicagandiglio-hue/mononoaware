import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const racconti = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/racconti" }),
  schema: z.object({
    // ─── CAMPI TUOI (obbligatori)
    title: z.string(),
    author: z.string(),
    originalLanguage: z.string(),
    translator: z.string().default("Gemini 3.1 Pro"),
    category: z.enum([
      "Naturalismo",
      "Romanzo dell'Io",
      "Estetismo",
      "Ero-Guro e Giallo",
      "Folklore e Fantasmi",
      "Satira e Critica Sociale",
      "Modernismo",
      "Realismo Storico",
    ]),
    country: z.string(),
    yearOriginal: z.number(),
    tags: z.array(z.string()).default([]),
    isDraft: z.boolean().default(false),
    description: z.string().max(160),

    // ─── CAMPI MIEI (tutti opzionali, con fallback)
    titleJp: z.string().optional(),
    originalTitle: z.string().optional(),
    period: z.string().optional(),
    readTime: z.number().optional(),
    note: z.string().optional(),
    excerpt: z.string().optional(),
    heroImage: z.string().optional(),
    oltreLeParole: z.string().optional(),
  }),
}); // ← mancava questa riga

// ─── AUTORI ──────────────────────────────────────────────────────────────────
const autori = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/autori" }),
  schema: z.object({
    name: z.string(),
    kanji:   z.string().optional(),
    anni:    z.string().optional(),
    nazione: z.string().default("Giappone"),
    temi:    z.string().optional(),
    foto:    z.string().optional(),
    excerpt: z.string().optional(),
    isDraft: z.boolean().default(false),
  }),
});

export const collections = { 'racconti': racconti, 'autori': autori };