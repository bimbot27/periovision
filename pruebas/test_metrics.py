from pathlib import Path
import tempfile
import unittest
from metrics_csv import summarize

HEAD = 'epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B)\n'

class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.path = Path(self.tmp.name) / 'serie.csv'
    def tearDown(self): self.tmp.cleanup()
    def write(self,text): self.path.write_text(text,encoding='utf-8'); return self.path
    def test_25_ultima_fila_y_maximo_no_son_lo_mismo(self):
        value=summarize(self.write(HEAD+'1,0.8,0.8,0.5,0.4\n2,0.4,0.4,0.7,0.6\n'))
        self.assertEqual(value['last_epoch']['epoch'],2)
        self.assertEqual(value['maximum_harmonic_row']['epoch'],1)
        self.assertFalse(value['checkpoint_identified'])
    def test_26_denominador_cero(self):
        value=summarize(self.write(HEAD+'1,0,0,0,0\n'))
        self.assertIsNone(value['last_epoch']['harmonic_precision_recall'])
    def test_27_rechaza_nan(self):
        with self.assertRaises(ValueError):summarize(self.write(HEAD+'1,nan,0.5,0.4,0.3\n'))
    def test_28_rechaza_epocas_repetidas(self):
        with self.assertRaises(ValueError):summarize(self.write(HEAD+'1,0.5,0.5,0.4,0.3\n1,0.6,0.5,0.4,0.3\n'))
    def test_29_rechaza_metricas_porcentuales_fuera_de_rango(self):
        with self.assertRaises(ValueError):summarize(self.write(HEAD+'1,50,0.5,0.4,0.3\n'))
    def test_30_rechaza_serie_vacia(self):
        with self.assertRaises(ValueError):summarize(self.write(HEAD))

if __name__=='__main__':unittest.main(verbosity=2)
