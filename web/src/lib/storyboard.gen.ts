// Generated from shared/storyboard.schema.json by npm run gen:types. Do not edit.

export interface Storyboard {
  /**
   * The lesson's title. At most 8 words.
   */
  title: string;
  /**
   * One sentence: what someone will understand after watching.
   */
  summary: string;
  scenes: {
    /**
     * Stable id: s1, s2, ... Never reuse an id within a lesson.
     */
    id: string;
    layout: "title" | "points" | "steps" | "compare" | "definition" | "example" | "code" | "flow" | "summary";
    /**
     * The scene's title on screen. At most 8 words.
     */
    heading: string;
    /**
     * One short line under the heading, or an empty string.
     */
    subheading: string;
    items: {
      /**
       * What appears on screen. Short: at most 9 words.
       */
      text: string;
      /**
       * A smaller second line, or an empty string.
       */
      detail: string;
      /**
       * Index of the narration sentence during which this item appears.
       */
      at: number;
      /**
       * On a code scene, the file line this item is about (highlighted when it appears); 0 otherwise.
       */
      line: number;
    }[];
    /**
     * In a repository lesson leave empty (it's filled from `source`); otherwise the code to show on a code scene, or an empty string.
     */
    code: string;
    source: {
      /**
       * A file path in the repository, or an empty string when the scene has no source.
       */
      path: string;
      /**
       * First line, counting from 1; 0 when there's no source.
       */
      start_line: number;
      /**
       * Last line, inclusive; 0 when there's no source.
       */
      end_line: number;
    };
    /**
     * What the voice says over this scene, written for the ear: 2 to 5 short sentences, plain words, numbers and symbols written the way they are said.
     */
    narration: string;
  }[];
}
