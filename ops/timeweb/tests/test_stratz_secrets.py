import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stratz_secrets import install_stratz


class StratzSecretInstallation(unittest.TestCase):
    def test_install_preserves_database_and_other_credentials(self):
        values={'DATABASE_URL':'unchanged','GEMINI_API_KEY':'old'}
        install_stratz(values,'synthetic.token-value')
        self.assertEqual(values,{'DATABASE_URL':'unchanged','GEMINI_API_KEY':'old','STRATZ_API_TOKEN':'synthetic.token-value'})

    def test_omitted_secret_does_not_clear_existing_configuration(self):
        values={'STRATZ_API_TOKEN':'existing'}
        install_stratz(values,None);install_stratz(values,'')
        self.assertEqual(values['STRATZ_API_TOKEN'],'existing')

    def test_reject_environment_injection_without_partial_mutation(self):
        for token in ('secret\nDATABASE_URL=replaced','${OTHER_KEY}','secret with spaces',[], 'x'*8193):
            values={'DATABASE_URL':'unchanged'}
            with self.subTest(token_type=type(token).__name__),self.assertRaises(ValueError):
                install_stratz(values,token)
            self.assertEqual(values,{'DATABASE_URL':'unchanged'})
