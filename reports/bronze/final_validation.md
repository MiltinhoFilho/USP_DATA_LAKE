# Valida??o final da camada Bronze

**Data e hora:** 2026-07-24T17:19:08.692045-03:00  
**Escopo:** 100 pares can?nicos JSON ? PDF (`usp_news_000001` a `usp_news_000100`)  
**Resultado:** 100/100 aprovados

## Metodologia

- O corpo do PDF foi gerado exclusivamente de `conteudo_texto`.
- A contagem de caracteres utiliza o texto can?nico sem caracteres de espa?amento, neutralizando apenas as quebras f?sicas de linha do layout PDF.
- Quebras f?sicas em t?tulos, autores e URLs, espa?os terminais e caracteres invis?veis normalizados pelo renderer n?o s?o diverg?ncias editoriais.
- A sequ?ncia completa de linhas vis?veis foi comparada com o plano determin?stico de renderiza??o.
- Cada par?grafo do JSON foi conferido no texto extra?do do PDF, na mesma ordem.
- T?tulo, autor, categoria, URL, in?cio, final, Unicode, metadados e hash da fonte foram validados.

## Documentos

| document_id | T?tulo | Caracteres JSON | Caracteres PDF | Diferen?a | Par?grafos | P?ginas | Status |
|---|---|---:|---:|---:|---:|---:|---|
| `usp_news_000001` | A verdadeira face da cultura de inovação | 5602 | 5602 | 0 | 18 | 3 | **APROVADO** |
| `usp_news_000002` | O primeiro passo na internacionalização da Com-Arte | 3549 | 3549 | 0 | 7 | 2 | **APROVADO** |
| `usp_news_000003` | Unesp recebe Colar de Honra ao Mérito Legislativo da Assembleia Legislativa de SP | 1611 | 1611 | 0 | 6 | 1 | **APROVADO** |
| `usp_news_000004` | “Revista Rasura”: educomunicação na‌ difusão científica e produção colaborativa de‌ conhecimento | 3930 | 3930 | 0 | 11 | 2 | **APROVADO** |
| `usp_news_000005` | “Revista USP” questiona os tempos e os espaços da educação | 3186 | 3186 | 0 | 11 | 2 | **APROVADO** |
| `usp_news_000006` | Alfabetização na idade certa mobiliza formações na Bahia | 7510 | 7510 | 0 | 22 | 3 | **APROVADO** |
| `usp_news_000007` | USP e Secretaria Municipal de Saúde selecionam estudantes para o PET-Saúde Clima | 2017 | 2017 | 0 | 6 | 1 | **APROVADO** |
| `usp_news_000008` | “Ser Transformado” é tema de exposição interativa na Biblioteca Sinhá Junqueira | 3418 | 3418 | 0 | 15 | 2 | **APROVADO** |
| `usp_news_000009` | USP sedia evento internacional sobre os avanços e desafios da educação básica no Brasil e em Angola | 2021 | 2021 | 0 | 13 | 2 | **APROVADO** |
| `usp_news_000010` | Quando o jogo sai da tela: os riscos da gamificação no cotidiano | 1219 | 1219 | 0 | 7 | 1 | **APROVADO** |
| `usp_news_000011` | USP Ribeirão Preto aproxima crianças e adolescentes da pesquisa científica | 4710 | 4710 | 0 | 20 | 2 | **APROVADO** |
| `usp_news_000012` | Vinte anos depois, o desafio continua no combate à violência contra mulheres e meninas | 4805 | 4805 | 0 | 14 | 2 | **APROVADO** |
| `usp_news_000013` | E-book apresenta estudos de caso e experiências brasileiras que promovem a saúde do solo | 5419 | 5419 | 0 | 14 | 2 | **APROVADO** |
| `usp_news_000014` | Doação de livros da USP em Ribeirão Preto fortalece formação jurídica em Timor-Leste | 4255 | 4255 | 0 | 17 | 2 | **APROVADO** |
| `usp_news_000015` | Pasteurização do passado: as máquinas de afeto | 6144 | 6144 | 0 | 33 | 3 | **APROVADO** |
| `usp_news_000016` | IDH recorde demonstra importância de políticas públicas e transformações sociais | 4282 | 4282 | 0 | 14 | 2 | **APROVADO** |
| `usp_news_000017` | Economia circular e invisibilidade de catadores são temas de exposição | 3272 | 3272 | 0 | 16 | 2 | **APROVADO** |
| `usp_news_000018` | Projeto da USP precisa de voluntários para mapear dificuldades sobre tecnologia na terceira idade | 1069 | 1069 | 0 | 5 | 1 | **APROVADO** |
| `usp_news_000019` | Livro resgata a quinta década de transformações na Faculdade de Medicina de Ribeirão Preto | 1926 | 1926 | 0 | 8 | 1 | **APROVADO** |
| `usp_news_000020` | Câmara dos Deputados aprova o fim da escala 6×1; PEC segue para o Senado | 4956 | 4956 | 0 | 13 | 2 | **APROVADO** |
| `usp_news_000021` | USP é a melhor universidade da América Latina e figura entre as 120 melhores do mundo em ranking internacional | 3137 | 3137 | 0 | 10 | 2 | **APROVADO** |
| `usp_news_000022` | OMS alerta para aumento de perda auditiva entre jovens | 2361 | 2361 | 0 | 10 | 2 | **APROVADO** |
| `usp_news_000023` | Atual crise de Ebola no Congo é mais transmissível que a epidemia de 2014 | 3084 | 3084 | 0 | 14 | 2 | **APROVADO** |
| `usp_news_000024` | Desaparecimento do site FiveThirtyEight é algo a se lamentar | 1674 | 1674 | 0 | 6 | 1 | **APROVADO** |
| `usp_news_000025` | São Paulo produz toneladas de lixo e recicla pouco | 827 | 827 | 0 | 5 | 1 | **APROVADO** |
| `usp_news_000026` | Morre a professora Angelita Habr-Gama, primeira mulher residente de cirurgia do Hospital das Clínicas da USP | 2977 | 2977 | 0 | 8 | 2 | **APROVADO** |
| `usp_news_000027` | Tecnologia desenvolvida na USP usa IA para identificar riscos no conteúdo digital acessado por crianças e adolescentes | 6115 | 6115 | 0 | 23 | 3 | **APROVADO** |
| `usp_news_000028` | Abertas as inscrições para exposição de pôsteres no Dia do Meio Ambiente | 877 | 877 | 0 | 5 | 1 | **APROVADO** |
| `usp_news_000029` | Conversaria | 582 | 582 | 0 | 8 | 1 | **APROVADO** |
| `usp_news_000030` | Livro traz pedagogias e vozes periféricas do hip hop | 2029 | 2029 | 0 | 11 | 1 | **APROVADO** |
| `usp_news_000031` | Psicologia indígena e impacto social | 5264 | 5264 | 0 | 6 | 2 | **APROVADO** |
| `usp_news_000032` | Estudo aponta que representatividade e diversidade entre professores beneficiam formação de alunos | 2778 | 2778 | 0 | 15 | 2 | **APROVADO** |
| `usp_news_000033` | Currículo eurocêntrico apaga culturas africanas desde a pré-escola | 6886 | 6886 | 0 | 30 | 3 | **APROVADO** |
| `usp_news_000034` | Exposição no MAC mostra a obra e a trajetória de Gilvan Samico | 3396 | 3396 | 0 | 18 | 2 | **APROVADO** |
| `usp_news_000035` | Mobilidade urbana e o futuro do transporte público no Brasil | 6046 | 6046 | 0 | 23 | 3 | **APROVADO** |
| `usp_news_000036` | Livro da Fuvest 2027, “Memórias de Martha” é tema de palestra na USP | 3406 | 3406 | 0 | 10 | 2 | **APROVADO** |
| `usp_news_000037` | Referência em patrimônio cultural e urbanismo histórico, Gabor Sonkoly participa de encontros na USP | 3401 | 3401 | 0 | 10 | 2 | **APROVADO** |
| `usp_news_000038` | Inscrições abertas para curso que usa orquídeas como modelo para estudar biologia e conservação | 1707 | 1707 | 0 | 8 | 1 | **APROVADO** |
| `usp_news_000039` | Cruesp divulga nota sobre negociação da campanha salarial com Fórum das Seis | 1406 | 1406 | 0 | 7 | 1 | **APROVADO** |
| `usp_news_000040` | Programa Universitário por um Dia celebra uma década de aproximação entre escola e Universidade | 3189 | 3189 | 0 | 14 | 2 | **APROVADO** |
| `usp_news_000041` | CEM transforma dados urbanos em ferramenta para pesquisas e políticas públicas | 3158 | 3158 | 0 | 10 | 2 | **APROVADO** |
| `usp_news_000042` | USP Ribeirão Preto promove quarta edição do Bike Tour com passeio histórico e arrecadação solidária | 1570 | 1570 | 0 | 6 | 1 | **APROVADO** |
| `usp_news_000043` | Canabidiol ganha espaço no esporte como aliado na recuperação muscular | 5177 | 5177 | 0 | 21 | 2 | **APROVADO** |
| `usp_news_000044` | Crescimento da prática esportiva impulsiona busca por eficiência na suplementação | 4997 | 4997 | 0 | 18 | 2 | **APROVADO** |
| `usp_news_000045` | Global study shows varied trend in obesity worldwide and criticizes the term epidemic | 11354 | 11354 | 0 | 45 | 5 | **APROVADO** |
| `usp_news_000046` | Aula aberta vai discutir espiritualidade durante tratamento de oncologia | 1027 | 1027 | 0 | 4 | 1 | **APROVADO** |
| `usp_news_000047` | Pró-reitor fala sobre desafios e projetos para o fortalecimento da pós-graduação da USP | 3317 | 3317 | 0 | 16 | 2 | **APROVADO** |
| `usp_news_000048` | Cidades inteligentes ou vigiadas? | 1466 | 1466 | 0 | 6 | 1 | **APROVADO** |
| `usp_news_000049` | Microscópio eletrônico mostra danos estruturais ao cabelo após descoloração, alisamento e calor | 7667 | 7667 | 0 | 31 | 3 | **APROVADO** |
| `usp_news_000050` | Guia para o bom e para o mau governo | 7513 | 7513 | 0 | 44 | 4 | **APROVADO** |
| `usp_news_000051` | USP quer fortalecer parceria com instituição alemã de financiamento | 2438 | 2438 | 0 | 9 | 2 | **APROVADO** |
| `usp_news_000052` | Fuvest divulga cronograma completo do vestibular da USP para ingresso em 2027 | 4960 | 4960 | 0 | 19 | 3 | **APROVADO** |
| `usp_news_000053` | O café e o despertar dos sentidos e emoções | 12024 | 12024 | 0 | 20 | 4 | **APROVADO** |
| `usp_news_000054` | Economia da USP lança campanha para financiar bolsas de intercâmbio e idiomas para estudantes negros | 4049 | 4049 | 0 | 20 | 2 | **APROVADO** |
| `usp_news_000055` | Estudantes da USP reinventam o drama e as paixões de Hamlet | 6483 | 6483 | 0 | 21 | 3 | **APROVADO** |
| `usp_news_000056` | A excelência dos programas de pós-graduação da USP | 2488 | 2488 | 0 | 8 | 1 | **APROVADO** |
| `usp_news_000057` | Ação climática e saúde ambiental pautam semana de debates na Faculdade de Saúde Pública da USP | 8609 | 8609 | 0 | 42 | 4 | **APROVADO** |
| `usp_news_000058` | Cruesp retoma discussões sobre o impacto da reforma tributária no financiamento das universidades | 2269 | 2269 | 0 | 9 | 2 | **APROVADO** |
| `usp_news_000059` | Incentivo ao doping busca aprimorar a performance esportiva, mas custo pode ser alto para os atletas | 8564 | 8564 | 0 | 33 | 4 | **APROVADO** |
| `usp_news_000060` | Edição de 28 de maio de 2026 | 1240 | 1240 | 0 | 3 | 1 | **APROVADO** |
| `usp_news_000061` | A nutrição clínica e sua importância na manutenção dos cuidados do paciente oncológico | 2299 | 2299 | 0 | 7 | 1 | **APROVADO** |
| `usp_news_000062` | Bolsa Família reduziu hospitalizações e aumentou empregabilidade, aponta estudo | 2807 | 2807 | 0 | 17 | 2 | **APROVADO** |
| `usp_news_000063` | Study suggests that sexual behavior of infant capuchin monkeys may have complex functions | 6306 | 6306 | 0 | 28 | 3 | **APROVADO** |
| `usp_news_000064` | Acordo entre Mercosul e União Europeia amplia debate sobre impactos no Brasil | 5937 | 5937 | 0 | 18 | 3 | **APROVADO** |
| `usp_news_000065` | Covid longa: abordagem inédita une 15 especialidades e reduz peregrinação de pacientes | 6661 | 6661 | 0 | 26 | 3 | **APROVADO** |
| `usp_news_000066` | E-book gratuito reúne opções de lanches sem glúten e de baixo custo desenvolvidas em pesquisas | 4824 | 4824 | 0 | 33 | 3 | **APROVADO** |
| `usp_news_000067` | YouTube: como a plataforma se tornou um ator político no debate público | 6882 | 6882 | 0 | 33 | 3 | **APROVADO** |
| `usp_news_000068` | ONU avança em decisão histórica sobre justiça climática | 882 | 882 | 0 | 7 | 1 | **APROVADO** |
| `usp_news_000069` | Concerto gratuito na USP mostra faces da violência e discute tema por meio da música | 2193 | 2193 | 0 | 8 | 2 | **APROVADO** |
| `usp_news_000070` | Exposição “Quilombo do Saracura Vai-Vai” tem visita mediada no Domingo na Yayá | 2696 | 2696 | 0 | 9 | 2 | **APROVADO** |
| `usp_news_000071` | Da ideia ao impacto: USP em Ribeirão Preto constrói rede para transformar pesquisa em soluções para a sociedade | 27390 | 27390 | 0 | 109 | 11 | **APROVADO** |
| `usp_news_000072` | Por um pacto uspiano | 4583 | 4583 | 0 | 10 | 2 | **APROVADO** |
| `usp_news_000073` | Uma Copa entre guerras e paz | 3362 | 3362 | 0 | 11 | 2 | **APROVADO** |
| `usp_news_000074` | Novo escritório da USP intensificará a integração entre a Universidade e a sociedade | 3440 | 3440 | 0 | 20 | 2 | **APROVADO** |
| `usp_news_000075` | Inscrições prorrogadas para a Escola de Inverno em Biociências e Biotecnologia | 1261 | 1261 | 0 | 5 | 1 | **APROVADO** |
| `usp_news_000076` | “Diálogos na USP” discute a influência dos Estados Unidos na ditadura militar | 1174 | 1174 | 0 | 2 | 1 | **APROVADO** |
| `usp_news_000077` | Quanto custa uma vida digna? Projeto estima os salários necessários para cobrir despesas | 7817 | 7817 | 0 | 25 | 3 | **APROVADO** |
| `usp_news_000078` | USP recebe encontro nacional sobre sustentabilidade nas universidades | 3340 | 3340 | 0 | 22 | 2 | **APROVADO** |
| `usp_news_000079` | Cientistas brasileiras debatem avanços e experiências de pesquisas em evento de 70 anos do Ipen | 2926 | 2926 | 0 | 7 | 2 | **APROVADO** |
| `usp_news_000080` | Peça conta a história do pugilista caribenho Emile Griffith | 2338 | 2338 | 0 | 7 | 1 | **APROVADO** |
| `usp_news_000081` | Encontro no Museu do Ipiranga busca reinterpretar modos de vida rurais | 7329 | 7329 | 0 | 24 | 3 | **APROVADO** |
| `usp_news_000082` | Queda da fertilidade masculina acende alerta sobre hábitos modernos e poluição | 6000 | 6000 | 0 | 26 | 3 | **APROVADO** |
| `usp_news_000083` | Edição de 27 de maio de 2026 | 1171 | 1171 | 0 | 3 | 1 | **APROVADO** |
| `usp_news_000084` | Olimpíada Brasileira de Robótica realiza etapa regional na USP em São Carlos | 5088 | 5088 | 0 | 18 | 3 | **APROVADO** |
| `usp_news_000085` | Os riscos do encolhimento de áreas verdes nas cidades | 2939 | 2939 | 0 | 13 | 2 | **APROVADO** |
| `usp_news_000086` | USP busca voluntários para pesquisa sobre uso de redes sociais | 902 | 902 | 0 | 5 | 1 | **APROVADO** |
| `usp_news_000087` | Solução de controvérsias no Mercosul: imagem de sistema ineficiente é equivocada | 6390 | 6390 | 0 | 26 | 3 | **APROVADO** |
| `usp_news_000088` | Protagonismo transgênero na ciência e saúde é tema de workshop | 1026 | 1026 | 0 | 4 | 1 | **APROVADO** |
| `usp_news_000089` | Conversa aborda diversidade e comunicação humanizada no cuidado à população LGBTQIA+ | 1377 | 1377 | 0 | 4 | 1 | **APROVADO** |
| `usp_news_000090` | Projeto da USP usa dança e cultura para fortalecer saúde emocional de adolescentes | 4703 | 4703 | 0 | 23 | 2 | **APROVADO** |
| `usp_news_000091` | Tornar crime o aumento abusivo do preço de combustíveis não é tão simples quanto parece | 4755 | 4755 | 0 | 14 | 2 | **APROVADO** |
| `usp_news_000092` | Brazilian researchers identify new species of microorganism in active volcano in Antarctica | 9161 | 9161 | 0 | 37 | 4 | **APROVADO** |
| `usp_news_000093` | Abertas as inscrições para o “Curso de Inverno em Saúde Pública” | 1445 | 1445 | 0 | 4 | 1 | **APROVADO** |
| `usp_news_000094` | Cinemas perdem público, mas bibliotecas e shows continuam com a mesma taxa de visitantes | 1901 | 1901 | 0 | 10 | 1 | **APROVADO** |
| `usp_news_000095` | Como São Paulo tem alocado recursos para educação?​ | 9809 | 9809 | 0 | 37 | 4 | **APROVADO** |
| `usp_news_000096` | Religião e ética se unem em diferentes crenças na sociedade atual | 1355 | 1355 | 0 | 6 | 1 | **APROVADO** |
| `usp_news_000097` | Doenças genéticas podem ser tratadas por transplante de mitocôndria | 897 | 897 | 0 | 7 | 1 | **APROVADO** |
| `usp_news_000098` | Manifestação dos dirigentes da USP sobre suspensão da reunião do Conselho Universitário | 4474 | 4474 | 0 | 8 | 2 | **APROVADO** |
| `usp_news_000099` | Nota dos pró-reitores da USP à comunidade acadêmica em apoio ao reitor e à vice-reitora da Universidade | 1621 | 1621 | 0 | 11 | 1 | **APROVADO** |
| `usp_news_000100` | Mentes em Pauta #13: Entre os espaços que ocupamos e as pessoas que nos transformam | 3463 | 3463 | 0 | 17 | 2 | **APROVADO** |

## Diverg?ncias

Nenhuma diverg?ncia identificada nos 100 pares.

## Quality Gate

- JSONs publicados: **100/100**
- PDFs gerados e abertos: **100/100**
- Pares textualmente equivalentes: **100/100**
- Pares com todos os par?grafos preservados: **100/100**
- Pares sem truncamento: **100/100**
- Pares sem caractere corrompido: **100/100**
- Pares sem HTML bruto vis?vel: **100/100**
- Pares com metadados preservados: **100/100**

**STATUS FINAL AUTOM?TICO: APROVADO**
