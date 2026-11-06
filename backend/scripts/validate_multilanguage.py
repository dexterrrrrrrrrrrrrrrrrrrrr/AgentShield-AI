"""Operator-only real language checks; readiness must pass before any program."""
import argparse
import json
import secrets
from app.config import Settings
from app.sandbox.manager import DockerAdapter

PROGRAMS = {
 'python': 'print("hello")',
 'c': '#include <stdio.h>\nint main(){puts("hello");}',
 'cpp': '#include <iostream>\nint main(){std::cout << "hello\\n";}',
 'java': 'public class Main {public static void main(String[] args){System.out.println("hello");}}',
 'javascript': 'console.log("hello");',
 'typescript': 'const message: string = "hello"; console.log(message);',
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-url', required=True)
    args = parser.parse_args()
    settings = Settings(jwt_secret=secrets.token_urlsafe(48), sandbox_enabled=True,
                        sandbox_docker_url=args.docker_url)
    adapter = DockerAdapter(settings)
    report = {'status':'BLOCKED', 'tests': []}
    for language in PROGRAMS:
        ready = adapter.readiness(language)
        if not ready['ready']:
            report['language'] = language
            report['reason'] = ready
            print(json.dumps(report, indent=2)); return 2
    report['status'] = 'PASS'
    for language, code in PROGRAMS.items():
        output = adapter.execute(code, language=language, stdin="staging validation\n")
        passed = output['status']=='completed' and output['stdout']=='hello\n'
        report['tests'].append({'language':language, 'passed':passed,
                               'compile_status':output.get('compile_status')})
        if not passed: report['status']='FAIL'
    print(json.dumps(report, indent=2))
    return 0 if report['status']=='PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
