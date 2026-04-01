import re
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand

from sales.translation_catalog import UI_TRANSLATIONS


ARABIC_TEXT_RE = re.compile(r'[\u0600-\u06FF][\u0600-\u06FFA-Za-z\s\-_/()0-9:%،.؟!$£]+')
SKIP_VALUES = {
    'csrfmiddlewaretoken',
}
SKIP_FILES = {
    'sales/translation_catalog.py',
}


class Command(BaseCommand):
    help = 'Extract Arabic UI strings from templates and Python files and report untranslated entries.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=200, help='Maximum number of results to print.')
        parser.add_argument(
            '--include-covered',
            action='store_true',
            help='Include strings already covered by the translation catalog.',
        )
        parser.add_argument(
            '--include-migrations',
            action='store_true',
            help='Include Django migration files in the scan output.',
        )
        parser.add_argument(
            '--include-tests',
            action='store_true',
            help='Include test files in the scan output.',
        )

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parents[3]
        search_roots = [base_dir / 'sales', base_dir / 'templates', base_dir / 'core']
        allowed_suffixes = {'.html', '.py', '.js'}
        include_migrations = options['include_migrations']
        include_tests = options['include_tests']

        counter = Counter()
        locations = defaultdict(list)

        for root in search_roots:
            if not root.exists():
                continue
            for file_path in root.rglob('*'):
                if file_path.suffix.lower() not in allowed_suffixes:
                    continue
                if '__pycache__' in file_path.parts:
                    continue
                if not include_migrations and 'migrations' in file_path.parts:
                    continue
                if not include_tests and any(part in {'tests', 'test'} for part in file_path.parts):
                    continue
                if not include_tests and file_path.name.startswith('test_'):
                    continue
                if not include_tests and file_path.name == 'tests.py':
                    continue
                self._collect_strings(base_dir, file_path, counter, locations)

        include_covered = options['include_covered']
        results = []
        for text, count in counter.most_common():
            covered = text in UI_TRANSLATIONS
            if not include_covered and covered:
                continue
            results.append((text, count, covered, locations[text]))

        limit = max(1, int(options['limit']))
        shown = results[:limit]
        if not shown:
            self.stdout.write(self.style.SUCCESS('No untranslated Arabic UI strings found in scanned files.'))
            return

        self.stdout.write(self.style.NOTICE(f'Found {len(results)} candidate strings. Showing first {len(shown)}.'))
        for text, count, covered, text_locations in shown:
            sample_locations = ', '.join(text_locations[:3])
            coverage_label = 'covered' if covered else 'missing'
            self.stdout.write(f'[{coverage_label}] {count:>3}x | {text} | {sample_locations}')

    def _collect_strings(self, base_dir, file_path, counter, locations):
        try:
            content = file_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            return

        relative_path = file_path.relative_to(base_dir).as_posix()
        if relative_path in SKIP_FILES:
            return
        for line_number, line in enumerate(content.splitlines(), start=1):
            for match in ARABIC_TEXT_RE.finditer(line):
                text = self._normalize(match.group(0))
                if not text or text in SKIP_VALUES or len(text) < 2:
                    continue
                counter[text] += 1
                if len(locations[text]) < 5:
                    locations[text].append(f'{relative_path}:{line_number}')

    @staticmethod
    def _normalize(text):
        text = ' '.join(text.split())
        return text.strip('"\'`{}[]<>|:;,. ').strip()