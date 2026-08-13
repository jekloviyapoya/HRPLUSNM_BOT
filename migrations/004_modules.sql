-- 004_modules.sql — pog'onali tarif o'rniga modullar ro'yxati
--
-- Sabab: mijozlarning ehtiyoji pog'onali emas. Birovga faqat xodimlar kerak,
-- boshqasiga xodimlar va ombor AI. Pog'onali tarifda o'rtadagi mijoz
-- keraksiz modullar uchun to'laydi yoki keragini ololmaydi.
--
-- plan ustuni o'chirilmaydi — tarixi saqlansin, lekin kod uni o'qimaydi.

ALTER TABLE license ADD COLUMN modules TEXT;

-- Mavjud tariflarni modullarga o'girish
UPDATE license SET modules = '["xodimlar","vazifalar","mijoz"]'
  WHERE modules IS NULL AND plan = 'boshlangich';

UPDATE license SET modules =
  '["xodimlar","vazifalar","hr","mijoz","ombor","nakladnoy","moliya"]'
  WHERE modules IS NULL AND plan = 'standart';

UPDATE license SET modules =
  '["xodimlar","vazifalar","hr","ombor","ombor_ai","nakladnoy",'
  || '"inventarizatsiya","moliya","marketing","mijoz"]'
  WHERE modules IS NULL AND plan = 'toliq';

-- Sinov muddatidagilarga hammasi ochiq: mijoz nima olishini ko'rib tanlasin
UPDATE license SET modules =
  '["xodimlar","vazifalar","hr","ombor","ombor_ai","nakladnoy",'
  || '"inventarizatsiya","moliya","marketing","mijoz"]'
  WHERE modules IS NULL AND state = 'trial';

UPDATE license SET modules = '[]' WHERE modules IS NULL;
