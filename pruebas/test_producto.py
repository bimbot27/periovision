import csv
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from core import (Case, DemoDetector, YoloDetector, ProductError, MAX_BYTES,
                  load_image, make_demo, audit_manifest, check_detections)

class ProductoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.demo=self.root/'DEMO01.png';make_demo(self.demo)
        self.case=Case(self.demo,'DEMO01')
    def tearDown(self):self.tmp.cleanup()
    def infer(self):self.case.quality(True);return self.case.infer(DemoDetector())

    def test_01_carga_valida_sin_metadatos_en_registro(self):
        self.assertEqual(self.case.image.size,(640,640))
        self.assertNotIn(str(self.demo),json.dumps(self.case.snapshot()))
        self.assertEqual(len(self.case.data['input_sha256']),64)
    def test_02_rechazo_formato(self):
        p=self.root/'entrada.txt';p.write_text('demo')
        with self.assertRaises(ProductError):load_image(p)
    def test_03_rechazo_archivo_corrupto(self):
        p=self.root/'vacio.png';p.write_bytes(b'')
        with self.assertRaises(ProductError):load_image(p)
    def test_04_rechazo_archivo_grande(self):
        p=self.root/'grande.png'
        with p.open('wb') as f:f.truncate(MAX_BYTES+1)
        with self.assertRaises(ProductError):load_image(p)
    def test_05_contenido_no_corresponde_a_extension(self):
        p=self.root/'oculto.png';Image.new('RGB',(12,12)).save(p,format='BMP')
        with self.assertRaises(ProductError):load_image(p)
    def test_06_no_evaluable_bloquea_inferencia(self):
        self.case.quality(False)
        with self.assertRaises(ProductError):self.case.infer(DemoDetector())
        self.assertEqual(self.case.data['runs'],[])
    def test_07_demo_resultado_prefijado_identificado(self):
        run=self.infer();self.assertEqual(run['original'][0]['box'],[100.,100.,220.,220.])
        self.assertFalse(run['model']['clinical_inference']);self.assertTrue(self.case.snapshot()['demo'])
    def test_08_demo_rechaza_otras_imagenes(self):
        p=self.root/'otra.png';Image.new('RGB',(640,640),'white').save(p)
        other=Case(p,'OTRA01');other.quality(True)
        with self.assertRaises(ProductError):other.infer(DemoDetector())
    def test_09_modelo_sin_permiso_bloqueado(self):
        with self.assertRaises(ProductError):YoloDetector(self.root/'no.pt',False)
    def test_10_pesos_ausentes_sin_fallback(self):
        with self.assertRaisesRegex(ProductError,'Modelo no disponible'):YoloDetector(self.root/'no.pt',True)
    def test_11_fallo_memoria_conserva_registro(self):
        self.infer();before=deepcopy(self.case.data)
        class Failed:
            mode='DEMO'
            def predict(self,image):raise MemoryError()
        with self.assertRaisesRegex(ProductError,'Memoria insuficiente'):self.case.infer(Failed())
        self.assertEqual(before,self.case.data)
    def test_12_corregir_preserva_original_y_historial(self):
        run=self.infer();items=deepcopy(run['original']);items[0]['box'][2]=225
        self.case.review('corregir','REV01',items)
        self.assertEqual(self.case.data['runs'][0]['original'][0]['box'][2],220)
        self.assertEqual(self.case.data['reviews'][0]['revised'][0]['box'][2],225)
        self.assertFalse(self.case.data['reviews'][0]['clinical_validation'])
    def test_13_corregir_fuera_de_imagen_rechazado(self):
        run=self.infer();run['original'][0]['box'][2]=1000
        with self.assertRaises(ProductError):self.case.review('corregir','REV01',run['original'])
        self.assertEqual(self.case.data['reviews'],[])
    def test_14_descartar_guarda_original(self):
        self.infer();self.case.review('descartar','REV01')
        self.assertEqual(self.case.data['reviews'][-1]['revised'],[])
        self.assertEqual(len(self.case.data['runs'][0]['original']),1)
    def test_15_nueva_corrida_no_hereda_revision(self):
        self.infer();self.case.review('aceptar','REV01');self.infer()
        self.assertEqual(self.case.snapshot()['status'],'provisional')
    def test_16_exporta_demo_y_provisional_sin_sobrescribir(self):
        self.infer();first=self.case.export(self.root/'salidas');second=self.case.export(self.root/'salidas')
        self.assertNotEqual(first,second)
        value=json.loads(first[0].read_text(encoding='utf-8'))
        self.assertTrue(value['demo']);self.assertEqual(value['status'],'provisional')
        with first[1].open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        self.assertEqual(rows[0]['record_type'],'original');self.assertEqual(rows[0]['class'],'DEMO')
    def test_17_exporta_original_y_revision(self):
        self.infer();self.case.review('aceptar','REV01');paths=self.case.export(self.root/'salidas')
        with paths[1].open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        self.assertEqual({r['record_type'] for r in rows},{'original','revision'})
    def test_18_codigos_no_admiten_formulas_o_rutas(self):
        for code in ['../fuera','=SUM(1)','nombre apellido']:
            with self.assertRaises(ProductError):Case(self.demo,code)
    def test_19_numeros_no_finitos_rechazados(self):
        with self.assertRaises(ProductError):check_detections([{'class':'DEMO','box':[0,0,20,20],'confidence':float('nan')}],(640,640),True)
    def manifest(self,rows):
        path=self.root/'manifiesto.csv'
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f);writer.writerow(['image_id','patient_code','sha256','subset']);writer.writerows(rows)
        return path
    def test_20_particion_detecta_paciente_compartido(self):
        p=self.manifest([['I01','P01','a'*64,'train'],['I02','P01','b'*64,'test']])
        value=audit_manifest(p);self.assertFalse(value['structural_check_passed'])
        self.assertIn('paciente',value['issues'][0])
    def test_21_particion_detecta_hash_duplicado(self):
        p=self.manifest([['I01','P01','a'*64,'train'],['I02','P02','a'*64,'val']])
        self.assertTrue(any('hash' in issue for issue in audit_manifest(p)['issues']))
    def test_22_particion_valida_no_certifica_clinica(self):
        p=self.manifest([['I01','P01','a'*64,'train'],['I02','P02','b'*64,'val'],['I03','P03','c'*64,'test']])
        value=audit_manifest(p);self.assertTrue(value['structural_check_passed'])
        self.assertFalse(value['clinical_validity']);self.assertFalse(value['data_authorization_verified'])
    def test_23_manifiesto_vacio_rechazado(self):
        self.assertFalse(audit_manifest(self.manifest([]))['structural_check_passed'])
    def test_24_sin_detecciones_conserva_advertencia(self):
        class Empty:
            mode='DEMO'
            def predict(self,image):return [],{'demo':True,'clinical_inference':False}
        self.case.quality(True);self.case.infer(Empty())
        self.assertEqual(self.case.data['runs'][0]['original'],[])
        self.assertIn('no significa ausencia',self.case.snapshot()['notice'])

if __name__=='__main__':unittest.main(verbosity=2)
