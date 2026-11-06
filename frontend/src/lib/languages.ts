export const STARTER_CODE = {
  python: 'print("Hello from the sandbox")\n',
  c: '#include <stdio.h>\n\nint main(void) {\n  puts("Hello from the sandbox");\n  return 0;\n}\n',
  cpp: '#include <iostream>\n\nint main() {\n  std::cout << "Hello from the sandbox\\n";\n  return 0;\n}\n',
  java: 'public class Main {\n  public static void main(String[] args) {\n    System.out.println("Hello from the sandbox");\n  }\n}\n',
  javascript: 'console.log("Hello from the sandbox");\n',
  typescript: 'const message: string = "Hello from the sandbox";\nconsole.log(message);\n',
};
export type LanguageId = keyof typeof STARTER_CODE;
export const LANGUAGE_NAMES: Record<LanguageId, string> = {
  python: "Python", c: "C", cpp: "C++", java: "Java", javascript: "JavaScript", typescript: "TypeScript",
};
export function languageName(id?: string) {
  return LANGUAGE_NAMES[id as LanguageId] || id || "Python";
}
export function registeredLanguage(id: string): id is LanguageId {
  return Object.hasOwn(STARTER_CODE, id);
}
