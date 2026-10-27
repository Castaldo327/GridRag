"""A duplicate launch must not rebuild the running demo's data or call models."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class StartupTests(unittest.TestCase):
    def test_busy_port_does_not_initialize_engine(self):
        with patch.object(sys,'argv',['server.py','--offline']), patch.object(server,'Server',side_effect=OSError('Address already in use')), patch.object(server,'Engine') as engine:
            with self.assertRaisesRegex(SystemExit,'Existing demo data was not changed'):
                server.main()
            engine.assert_not_called()

if __name__=='__main__': unittest.main()
