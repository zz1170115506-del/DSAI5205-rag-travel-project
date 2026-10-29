# DSAI5205 English Presentation Guide

## Opening statement

We implemented HK Slow, an interactive Hong Kong travel assistant that combines Retrieval-Augmented Generation, MCP tools and supplementary map retrieval. The system uses training-free strategies to retrieve source evidence, answer with citations and help users create and refine an itinerary. RAG supplies knowledge, MCP exposes tools, LangGraph coordinates state and decisions, and a local algorithm performs itinerary scheduling.

## Suggested fourteen-minute talk

| Time | Speaker topic | Key point |
| --- | --- | --- |
| 1 minute | Problem and users | Visitors need source-backed suggestions and editable travel plans. |
| 3 minutes | Method | Explain the two evidence paths and distinguish RAG from MCP. |
| 2 minutes | Implementation | Show the architecture and structured conversation state. |
| 5 minutes | Demonstration | Run the sequence below and inspect evidence. |
| 3 minutes | Discussion | Explain benefits, validation and limitations. |

Leave four minutes for questions. Every member must speak and be ready to explain their contribution. The report is at most ten pages excluding references, using Introduction, Method, Implementation, Demonstration and Discussion. The course weights are presentation/demonstration 45%, report 35% and slides 20%.

## Rehearsal checklist

- Use the English edition of the main application; verify the actual deployed commit if using Render.
- Check the model, embedding and map readiness under Concept Demo.
- Enable Smart Assist for the generation demonstration. A local-only answer is not evidence of a successful cloud-model call.
- Confirm `embedding_used=true` on a real hybrid-retrieval turn. A configured model or existing index alone does not prove it was used.
- Keep the same page open for follow-ups. Anonymous sessions do not support shared-history browsing or refresh restoration.
- Save a short recording of an actual successful run, labelled with its version and conditions. Do not present a fixture response as a live provider call.

## Five-minute demo script

### 1. Source-backed place question

Ask: **“What cultural places can I visit in Central?”**

Explain: the system searches its curated collection using BM25 and, when available, local BGE embeddings. RRF combines the rankings. The model uses returned evidence and cites canonical place IDs.

Show: a cited place, its official source, and the `search_places` trace. Explain that citation-ID validation does not prove every generated sentence is true.

### 2. Tool-based itinerary

Select **Tai Kwun** and **PMQ**, enable **Plan selected places only**, and ask:

**“Plan my selected places over three days at a relaxed pace.”**

Show the full calendar and selected stops. Explain that the local planner applies constraints, groups by neighbourhood and orders visits heuristically. Free days are explicit when selected places do not fill the trip; the system should not invent extra destinations.

### 3. Contextual changes

Continue in the same conversation:

1. **“Add one more day.”** The total should change from three to four.
2. **“Make it one day.”** The total should become one, retaining feasible selected places.

Explain the difference between an increment and an absolute setting. The backend validates edits and updates an existing end date. An impossible duration or place capacity should produce a clear constraint response.

### 4. Map-augmented retrieval

Clear restrictive preferences, start a new chat and ask:

**“Which shopping malls can I visit in Kowloon?”**

Explain: local category matches are insufficient, so the chat service queries Hong Kong map evidence. A shopping street or museum must not substitute for a mall.

Show: the `map_search` trace, provider candidates and original map links. If generation succeeds, show `[map-1]` and `map_rag_used=true`. If it fails, explain the actual failure and the evidence still available. External POIs are not yet automatically added to the itinerary.

### 5. Information boundary

Ask: **“What time do these malls open tomorrow?”**

Explain that the available POI fields cannot verify current opening hours. The assistant should direct the user to an official source rather than invent a schedule.

## Questions the group should be able to answer

**Why use RAG?** To provide task-specific external evidence and inspectable sources instead of relying only on model memory.

**What does MCP add?** A standard tool-access interface. The local retrieval, detail, transfer and itinerary tools use MCP stdio. In-process state edits and AMap Web Service requests are separate paths.

**Is the planner itself RAG?** Its scheduling algorithm is not RAG. Retrieved evidence supports recommendations; local constraints and heuristics build the itinerary.

**Why combine sparse and dense retrieval?** Names and exact terms benefit from lexical retrieval; paraphrases may benefit from embeddings. Fusion is a design choice whose effect must be evaluated, not assumed.

**Are all map results verified knowledge?** No. They are provider evidence with source/time information and validation boundaries, not manually reviewed additions to the curated collection.

**What do passing tests prove?** They support implementation correctness for tested cases. Fixture calls, handwritten evaluation questions and single real-provider examples do not establish general answer accuracy or provider reliability.

**Why retain original-language data?** Canonical identifiers, enums and original sources support reproducibility and compatibility. English display text is a separate layer; the UI does not invent translations for unknown provider details.

## Submission and contribution notes

Prepare slides and a standalone report using the course structure. Include screenshots from the final version. Record each member's actual work and understanding, and disclose GenAI assistance appropriately. Do not claim experiments, live calls or capabilities that were not completed and checked.
